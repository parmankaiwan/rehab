"use client";
/* eslint-disable @next/next/no-img-element */

import Link from "next/link";
import { Camera, Check, Download, Expand, Plus, RotateCcw, Square, Trash2, Video as VideoIcon } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useBrowserPose, type BrowserPoseObservation, type BrowserStillCapture } from "@/hooks/useBrowserPose";
import { captureQuality, isEditableTarget, observationsJsonl, selectRecorderFormat } from "@/lib/browserCapture";
import type { BrowserCollectionDataset, BrowserCollectionSample, CaptureState } from "@/types/browserCollection";

const api = "/api/master/data";
type Mode = "STILL" | "VIDEO";
type Source = "BROWSER_MEDIAPIPE" | "FLEXMAP_ENGINE";
type StudioView = "OVERVIEW" | "COLLECT" | "SAMPLES" | "SETTINGS";
type ReviewCapture = { mode: Mode; media: Blob | null; mediaUrl: string | null; observations: BrowserPoseObservation[]; still?: BrowserStillCapture; startedAt: number; endedAt: number; wallClock: string; requestedDurationMs: number | null; interrupted: boolean; mimeType: string | null; extension: string | null; width: number; height: number };

function sleep(ms: number) { return new Promise((resolve) => window.setTimeout(resolve, ms)); }
function jsonBlob(value: unknown) { return new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }); }

export function CvCollectionStudio() {
  const datasetId = useSearchParams().get("dataset") || "";
  const [dataset, setDataset] = useState<BrowserCollectionDataset | null>(null);
  const [storageReady, setStorageReady] = useState(false);
  const [missingStorage, setMissingStorage] = useState<string[]>([]);
  const [source, setSource] = useState<Source>("BROWSER_MEDIAPIPE");
  const [view, setView] = useState<StudioView>("COLLECT");
  const [mode, setMode] = useState<Mode>("STILL");
  const [labelId, setLabelId] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [protocolId, setProtocolId] = useState("");
  const [notes, setNotes] = useState("");
  const [countdown, setCountdown] = useState<3 | 5>(3);
  const [duration, setDuration] = useState<5 | 10 | 15 | 30 | 0>(5);
  const [restSeconds, setRestSeconds] = useState(0);
  const [target, setTarget] = useState(10);
  const [savedCount, setSavedCount] = useState(0);
  const [mirror, setMirror] = useState(true);
  const [skeleton, setSkeleton] = useState(true);
  const [landmarksOnly, setLandmarksOnly] = useState(false);
  const [deviceId, setDeviceId] = useState("");
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [captureState, setCaptureState] = useState<CaptureState>("IDLE");
  const [countdownValue, setCountdownValue] = useState(0);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [review, setReview] = useState<ReviewCapture | null>(null);
  const [error, setError] = useState("");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [newLabel, setNewLabel] = useState("");
  const [recent, setRecent] = useState<BrowserCollectionSample[]>([]);
  const [idempotencyKey, setIdempotencyKey] = useState("");
  const operationRef = useRef(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const stopRef = useRef<((interrupted?: boolean) => void) | null>(null);
  const reviewRef = useRef<ReviewCapture | null>(null);
  const browserEnabled = source === "BROWSER_MEDIAPIPE" && view === "COLLECT";
  const mediaDisabled = landmarksOnly || dataset?.allow_raw_media === false;
  const pose = useBrowserPose(browserEnabled, deviceId || undefined);
  const active = ["PREFLIGHT", "COUNTDOWN", "CAPTURING", "RECORDING", "FINALIZING", "UPLOADING", "VALIDATING"].includes(captureState);
  const selectedLabel = dataset?.labels?.find((label) => label.label_id === labelId);

  const refreshDataset = useCallback(async () => {
    if (!datasetId) return;
    const [datasetResponse, statusResponse] = await Promise.all([fetch(`${api}/browser-collections/${datasetId}`, { cache: "no-store" }), fetch(`${api}/browser-collections/status`, { cache: "no-store" })]);
    if (!datasetResponse.ok) { setError((await datasetResponse.json().catch(() => ({}))).detail || "Dataset could not be loaded."); return; }
    const loaded: BrowserCollectionDataset = await datasetResponse.json();
    const status = statusResponse.ok ? await statusResponse.json() : { configured: false, missing: [] };
    setDataset(loaded); setRecent((loaded.samples || []).slice(0, 8)); setStorageReady(status.configured); setMissingStorage(status.missing || []);
    setLabelId((current) => current || loaded.labels?.find((label) => !label.archived)?.label_id || "");
    setSessionId((current) => current || loaded.session_id || ""); setProtocolId((current) => current || loaded.protocol_id || "");
    if (loaded.permitted_capture_types === "STILL") setMode("STILL");
    if (loaded.permitted_capture_types === "VIDEO") setMode("VIDEO");
  }, [datasetId]);

  useEffect(() => { void refreshDataset(); }, [refreshDataset]);
  useEffect(() => { reviewRef.current = review; }, [review]);
  useEffect(() => () => { if (reviewRef.current?.mediaUrl) URL.revokeObjectURL(reviewRef.current.mediaUrl); }, []);
  useEffect(() => {
    if (!browserEnabled || pose.state === "DENIED" || pose.state === "UNAVAILABLE") return;
    navigator.mediaDevices.enumerateDevices().then((items) => setDevices(items.filter((item) => item.kind === "videoinput"))).catch(() => undefined);
  }, [browserEnabled, pose.state]);
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => { if (active || review) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", beforeUnload); return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [active, review]);

  const discard = useCallback(() => {
    if (reviewRef.current?.mediaUrl) URL.revokeObjectURL(reviewRef.current.mediaUrl);
    setReview(null); setError(""); setUploadProgress(0); setIdempotencyKey(""); setCaptureState("IDLE"); operationRef.current = false;
  }, []);

  const countdownThen = useCallback(async (action: () => Promise<void>) => {
    if (operationRef.current) return;
    operationRef.current = true; setError(""); setCaptureState("PREFLIGHT");
    if (!dataset || !labelId || !subjectId.trim()) { setError("Select a dataset label and enter a subject code."); setCaptureState("ERROR"); operationRef.current = false; return; }
    if (source !== "BROWSER_MEDIAPIPE") { setError("Use the existing module collector for FlexMap Engine captures."); setCaptureState("ERROR"); operationRef.current = false; return; }
    if (pose.state !== "LIVE" && pose.state !== "CAMERA_READY") { setError("Wait for the browser camera and MediaPipe model to become ready."); setCaptureState("ERROR"); operationRef.current = false; return; }
    setCaptureState("COUNTDOWN");
    for (let value = countdown; value > 0; value -= 1) { setCountdownValue(value); await sleep(1000); }
    setCountdownValue(0);
    try { await action(); } catch (cause) { setError(cause instanceof Error ? cause.message : "Capture failed."); setCaptureState("ERROR"); operationRef.current = false; }
  }, [countdown, dataset, labelId, pose.state, source, subjectId]);

  const captureStill = useCallback(() => countdownThen(async () => {
    setCaptureState("CAPTURING"); const captured = await pose.captureStill(); const now = performance.now();
    const item: ReviewCapture = { mode: "STILL", media: mediaDisabled ? null : captured.image, mediaUrl: mediaDisabled ? null : URL.createObjectURL(captured.image), observations: [captured.observation], still: captured, startedAt: now, endedAt: now, wallClock: new Date().toISOString(), requestedDurationMs: null, interrupted: false, mimeType: mediaDisabled ? null : captured.image.type, extension: mediaDisabled ? null : ".jpg", width: captured.width, height: captured.height };
    setReview(item); setIdempotencyKey(crypto.randomUUID()); setCaptureState("REVIEW"); operationRef.current = false;
  }), [countdownThen, mediaDisabled, pose]);

  const startVideo = useCallback(() => countdownThen(async () => {
    const stream = pose.getStream();
    if (!stream) throw new Error("The shared camera stream is unavailable.");
    if (!window.MediaRecorder) throw new Error("This browser does not support MediaRecorder.");
    const format = selectRecorderFormat(MediaRecorder.isTypeSupported.bind(MediaRecorder));
    if (!format) throw new Error("No supported WebM or MP4 recording format was found.");
    const recorder = new MediaRecorder(stream, { mimeType: format.mimeType, videoBitsPerSecond: 3_000_000 });
    recorderRef.current = recorder;
    const chunks: Blob[] = []; const observations: BrowserPoseObservation[] = []; const startedAt = performance.now(); const wallClock = new Date().toISOString();
    let interrupted = false; let stopping = false; let timer = 0; let limitTimer = 0; let unsubscribe: () => void = () => undefined;
    const maximumMs = duration ? duration * 1000 : 120_000;
    const finalized = new Promise<void>((resolve, reject) => {
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      recorder.onerror = () => { interrupted = true; reject(new Error("The browser recorder reported an error.")); };
      recorder.onstop = () => resolve();
    });
    const stop = (wasInterrupted = false) => { if (stopping) return; stopping = true; interrupted ||= wasInterrupted; setCaptureState("FINALIZING"); recorder.stop(); };
    stopRef.current = stop;
    const ended = () => stop(true); stream.getVideoTracks().forEach((track) => track.addEventListener("ended", ended, { once: true }));
    unsubscribe = pose.subscribe((observation) => observations.push(observation));
    recorder.start(1000); setCaptureState("RECORDING");
    timer = window.setInterval(() => setElapsedMs(performance.now() - startedAt), 100);
    limitTimer = window.setTimeout(() => stop(duration === 0), maximumMs);
    if (duration) window.setTimeout(() => stop(false), duration * 1000);
    await finalized;
    window.clearInterval(timer); window.clearTimeout(limitTimer); unsubscribe(); stopRef.current = null; recorderRef.current = null;
    stream.getVideoTracks().forEach((track) => track.removeEventListener("ended", ended));
    const endedAt = performance.now(); const media = mediaDisabled ? null : new Blob(chunks, { type: recorder.mimeType || format.mimeType });
    if (!mediaDisabled && (!media || media.size === 0)) throw new Error("Recorder produced an empty video.");
    const settings = stream.getVideoTracks()[0]?.getSettings();
    const item: ReviewCapture = { mode: "VIDEO", media, mediaUrl: media ? URL.createObjectURL(media) : null, observations, startedAt, endedAt, wallClock, requestedDurationMs: duration ? duration * 1000 : null, interrupted, mimeType: media?.type || null, extension: media ? format.extension : null, width: settings?.width || 1280, height: settings?.height || 720 };
    setReview(item); setIdempotencyKey(crypto.randomUUID()); setCaptureState(interrupted ? "INTERRUPTED" : "REVIEW"); setElapsedMs(endedAt - startedAt); operationRef.current = false;
  }), [countdownThen, duration, mediaDisabled, pose]);

  const triggerCapture = useCallback(() => mode === "STILL" ? void captureStill() : void startVideo(), [captureStill, mode, startVideo]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => { if (isEditableTarget(event.target)) return; if (event.code === "Space" && captureState === "IDLE") { event.preventDefault(); triggerCapture(); } if (event.key.toLowerCase() === "r" && review) discard(); };
    window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key);
  }, [captureState, discard, review, triggerCapture]);

  const artifacts = useMemo(() => {
    if (!review) return null;
    const quality = captureQuality(review.observations);
    const measurementRows = review.observations.map((item) => ({ poseResultSequenceId: item.poseResultSequenceId, playbackOffsetMs: Math.max(0, item.monotonicTimestampMs - review.startedAt), components: item.snapshot?.components || null, classifierOutput: item.snapshot ? { overall_state: item.snapshot.overall_state, ready: item.snapshot.ready, ready_progress: item.snapshot.ready_progress, note: "Browser heuristic; not calibrated confidence" } : null }));
    const metadata = { schema_version: "1.0", dataset_id: datasetId, label_id: labelId, label_at_capture: selectedLabel?.name || "", sample_type: review.mode, source: "BROWSER_MEDIAPIPE", subject_id: subjectId.trim(), session_id: sessionId || null, protocol_id: protocolId || null, trial_id: crypto.randomUUID(), attempt_number: 1, notes, capture_state: review.interrupted ? "INTERRUPTED" : "COMPLETE", technical_quality: quality.technicalQuality, tracking_quality: quality.trackingQuality, wall_clock_created_at: review.wallClock, performance_time_origin_ms: performance.timeOrigin, monotonic_start_ms: review.startedAt, monotonic_end_ms: review.endedAt, requested_duration_ms: review.requestedDurationMs, observed_duration_ms: review.endedAt - review.startedAt, verified_media_duration_ms: null, timing_association: "TIMESTAMP_NEAREST_APPROXIMATE", timing_uncertainty_ms: review.observations.length > 1 ? (review.endedAt - review.startedAt) / review.observations.length : null, synchronization_status: "NOT_CONFIGURED", media_mime_type: review.mimeType, media_extension: review.extension, width: review.width, height: review.height, mirrored_preview: mirror, orientation: review.width === review.height ? "SQUARE" : review.width > review.height ? "LANDSCAPE" : "PORTRAIT", model_configuration: review.observations[0]?.model || {}, classifier_output: review.observations.at(-1)?.snapshot ? { overall_state: review.observations.at(-1)?.snapshot?.overall_state, ready: review.observations.at(-1)?.snapshot?.ready } : null, permission_scope: { raw_media: !!review.media, annotated_media: false, thumbnails: false, export: true }, observation_count: review.observations.length };
    const poseText = review.mode === "VIDEO" ? observationsJsonl(review.observations, review.startedAt) : JSON.stringify(review.observations, null, 2);
    return { metadata, quality, poseText, measurementRows };
  }, [datasetId, labelId, mirror, notes, protocolId, review, selectedLabel?.name, sessionId, subjectId]);

  function buildFormData() {
    if (!review || !artifacts) throw new Error("No capture is available for upload.");
    const data = new FormData(); data.append("metadata", JSON.stringify(artifacts.metadata)); data.append("idempotency_key", idempotencyKey);
    if (review.media) data.append("media", review.media, review.mode === "STILL" ? "image.jpg" : `video${review.extension}`);
    data.append("pose_observations", new Blob([artifacts.poseText], { type: review.mode === "VIDEO" ? "application/x-ndjson" : "application/json" }), review.mode === "VIDEO" ? "pose_observations.jsonl" : "pose_observations.json");
    data.append("measurements", jsonBlob(artifacts.measurementRows), "measurements.json"); data.append("events", jsonBlob([{ type: "CAPTURE_START", source: "BROWSER", monotonicMs: review.startedAt }, { type: review.interrupted ? "CAPTURE_INTERRUPTED" : "CAPTURE_END", source: "BROWSER", monotonicMs: review.endedAt }]), "events.json");
    data.append("quality_report", jsonBlob({ ...artifacts.quality, missingLandmarksPreserved: true }), "quality_report.json");
    data.append("manifest", jsonBlob({ schema_version: "1.0", raw_media: review.media ? { name: review.mode === "STILL" ? "image.jpg" : `video${review.extension}`, mime_type: review.mimeType, role: "RAW" } : null, observations: review.mode === "STILL" ? "pose_observations.json" : "pose_observations.jsonl", timingAssociation: "TIMESTAMP_NEAREST_APPROXIMATE", synchronization_status: "NOT_CONFIGURED" }), "manifest.json"); return data;
  }

  async function save(andNext = false) {
    if (!storageReady) { setError(`Cloud save is blocked. Missing: ${missingStorage.join(", ")}. Use local export instead.`); setCaptureState("UPLOAD_FAILED"); return; }
    setCaptureState("UPLOADING"); setError(""); setUploadProgress(0);
    try {
      const saved = await new Promise<BrowserCollectionSample>((resolve, reject) => { const request = new XMLHttpRequest(); request.open("POST", `${api}/browser-collections/samples`); request.upload.onprogress = (event) => event.lengthComputable && setUploadProgress(Math.round(event.loaded / event.total * 100)); request.onerror = () => reject(new Error("Network error while uploading.")); request.onload = () => { const body = JSON.parse(request.responseText || "{}"); if (request.status >= 200 && request.status < 300) resolve(body); else reject(new Error(body.detail || "Upload failed.")); }; request.send(buildFormData()); });
      setCaptureState("VALIDATING"); setRecent((items) => [saved, ...items].slice(0, 8)); setSavedCount((value) => value + 1); setUploadProgress(100); setCaptureState("SAVED");
      if (andNext) { if (restSeconds) await sleep(restSeconds * 1000); discard(); }
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Upload failed."); setCaptureState("UPLOAD_FAILED"); }
  }

  function exportLocal() {
    if (!review || !artifacts) return;
    const packageBlob = jsonBlob({ warning: "Downloaded, not saved to Dataset Vault.", metadata: artifacts.metadata, poseObservations: review.observations, measurements: artifacts.measurementRows, quality: artifacts.quality });
    const download = (blob: Blob, name: string) => { const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = name; anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); };
    download(packageBlob, `flexmap-${review.mode.toLowerCase()}-package.json`); if (review.media) download(review.media, `flexmap-raw${review.extension}`);
  }

  async function addLabel() {
    if (!dataset || !newLabel.trim() || active) return;
    const response = await fetch(`${api}/browser-collections/${dataset.dataset_id}/labels`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: newLabel }) });
    const body = await response.json().catch(() => ({})); if (!response.ok) { setError(body.detail || "Label creation failed."); return; }
    setDataset({ ...dataset, labels: [...(dataset.labels || []), body] }); setLabelId(body.label_id); setNewLabel("");
  }

  async function updateDataset(values: { name?: string; description?: string; instructions?: string; archived?: boolean }) {
    if (!dataset || active || review) return;
    const response = await fetch(`${api}/browser-collections/${dataset.dataset_id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) { setError(body.detail || "Dataset update failed."); return; }
    setDataset({ ...dataset, ...body }); setError("");
  }

  if (!datasetId) return <section><h1>CV Collection Studio</h1><p className="master-alert">Choose a dataset before opening the Studio.</p><Link href="/master/cv-data">Back to CV Collection</Link></section>;
  if (!dataset) return <section><h1>CV Collection Studio</h1><p>{error || "Loading dataset…"}</p></section>;
  const locked = active || !!review;
  const remaining = duration ? Math.max(0, duration * 1000 - elapsedMs) : null;

  return <section className="cv-studio">
    <nav className="breadcrumbs"><Link href="/master/cv-data">CV Collection</Link><span>›</span><strong>{dataset.name}</strong></nav>
    <header><div><span className="eyebrow">Browser-owned research capture</span><h1>{dataset.name}</h1><p>{dataset.instructions || dataset.description || "Collect labelled posture samples."}</p></div><div className={`capture-state state-${captureState.toLowerCase()}`}>{captureState.replaceAll("_", " ")}</div></header>
    <div className="dataset-tabs" role="tablist">{(["OVERVIEW", "COLLECT", "SAMPLES", "SETTINGS"] as StudioView[]).map((item) => <button role="tab" aria-selected={view === item} className={view === item ? "active" : ""} disabled={active || !!review} key={item} onClick={() => setView(item)}>{item[0] + item.slice(1).toLowerCase()}</button>)}</div>
    {!storageReady && <div className="collection-storage is-blocked"><strong>Cloud save unavailable</strong><span>Missing {missingStorage.join(", ")}. Local export remains available after capture.</span></div>}
    {error && <p className="master-alert">{error}</p>}
    {view === "OVERVIEW" && <div className="dataset-overview"><article className="master-card"><h2>Dataset overview</h2><p>{dataset.description || "No description"}</p><dl><div><dt>Rehabilitation module</dt><dd>{dataset.rehabilitation_module_id}</dd></div><div><dt>Capture types</dt><dd>{dataset.permitted_capture_types}</dd></div><div><dt>Camera view</dt><dd>{dataset.camera_view}</dd></div><div><dt>Source</dt><dd>BROWSER_MEDIAPIPE</dd></div></dl></article><article className="master-card"><h2>Labels</h2><div className="label-folders">{dataset.labels?.map((label) => <span key={label.label_id}>{label.display_name}</span>)}</div><p>Adding this research dataset does not publish a Patient Mode exercise.</p></article></div>}
    {view === "SAMPLES" && <section className="sample-gallery"><h2>Samples</h2>{recent.map((sample) => <Link key={sample.sample_id} href={`/master/dataset/${sample.sample_id}`}><span className="sample-badge">{sample.sample_type}</span><strong>{sample.label_at_capture}</strong><span>{sample.subject_id}</span><span>{sample.technical_quality} · {sample.review_status}</span><small>{new Date(sample.created_at).toLocaleString()}</small></Link>)}{!recent.length && <p>No samples have been saved in this dataset.</p>}</section>}
    {view === "SETTINGS" && <form className="dataset-settings" onSubmit={(event) => { event.preventDefault(); const data = new FormData(event.currentTarget); void updateDataset({ name: String(data.get("name")), description: String(data.get("description")), instructions: String(data.get("instructions")) }); }}><h2>Dataset settings</h2><label>Name<input name="name" defaultValue={dataset.name} required/></label><label>Description<textarea name="description" defaultValue={dataset.description}/></label><label>Capture instructions<textarea name="instructions" defaultValue={dataset.instructions}/></label><button className="primary">Save settings</button><button type="button" className="danger" onClick={() => void updateDataset({ archived: !dataset.archived })}>{dataset.archived ? "Restore dataset" : "Archive dataset"}</button><p>Archiving never deletes samples or rewrites their original label.</p></form>}
    <div className="cv-studio-grid" style={{display: view === "COLLECT" ? undefined : "none"}}>
      <div className="cv-stage" ref={(node) => { if (node && captureState === "COUNTDOWN") node.dataset.counting = "true"; }}>
        {review ? <div className="cv-review-media">{review.mediaUrl ? review.mode === "STILL" ? <img src={review.mediaUrl} alt="Clean captured camera frame"/> : <video src={review.mediaUrl} controls playsInline/> : <div className="landmarks-review"><Check/><strong>Landmarks-only capture</strong><span>No image or video was retained.</span></div>}</div> : <><video ref={pose.videoRef} className={mirror ? "browser-camera-video" : ""} muted playsInline/><PoseOverlay observation={pose.getLatestObservation()} visible={skeleton}/></>}
        {countdownValue > 0 && <div className="studio-countdown" aria-live="assertive">{countdownValue}</div>}
        {captureState === "RECORDING" && <div className="recording-banner"><i/> REC {Math.floor(elapsedMs / 1000)}s {remaining != null ? `· ${Math.ceil(remaining / 1000)}s left` : "· manual"}</div>}
        {!review && pose.state !== "LIVE" && <div className="camera-state"><Camera/><strong>{pose.state.replaceAll("_", " ")}</strong><span>{pose.error || "MediaPipe initializes after camera permission is granted."}</span></div>}
        <button className="studio-fullscreen" onClick={(event) => event.currentTarget.parentElement?.requestFullscreen()}><Expand/>Fullscreen</button>
      </div>
      <aside className="studio-controls">
        <div className="studio-tabs"><button className={source === "BROWSER_MEDIAPIPE" ? "active" : ""} disabled={locked} onClick={() => setSource("BROWSER_MEDIAPIPE")}>Browser MediaPipe</button><button className={source === "FLEXMAP_ENGINE" ? "active" : ""} disabled={locked} onClick={() => setSource("FLEXMAP_ENGINE")}>FlexMap Engine</button></div>
        {source === "FLEXMAP_ENGINE" ? <div className="engine-notice"><strong>Established engine pipeline</strong><p>The Python engine uses its own recorder and provenance. New browser Studio actions are disabled here.</p><Link className="primary" href={`/master/cv-data/${dataset.rehabilitation_module_id.toLowerCase().replaceAll("_", "-")}`}>Open engine collector</Link></div> : <>
          <label>Posture label<select disabled={locked} value={labelId} onChange={(event) => setLabelId(event.target.value)}>{dataset.labels?.filter((label) => !label.archived).map((label) => <option key={label.label_id} value={label.label_id}>{label.display_name}</option>)}</select></label>
          {!locked && <div className="inline-label"><input aria-label="New posture label" placeholder="New label" value={newLabel} onChange={(event) => setNewLabel(event.target.value)}/><button onClick={() => void addLabel()}><Plus/>Add</button></div>}
          <label>Subject code*<input disabled={locked} value={subjectId} maxLength={64} pattern="[A-Za-z0-9_-]+" onChange={(event) => setSubjectId(event.target.value)}/></label>
          <div className="field-pair"><label>Session<input disabled={locked} value={sessionId} onChange={(event) => setSessionId(event.target.value)}/></label><label>Protocol<input disabled={locked} value={protocolId} onChange={(event) => setProtocolId(event.target.value)}/></label></div>
          <div className="mode-switch"><button className={mode === "STILL" ? "active" : ""} disabled={locked || dataset.permitted_capture_types === "VIDEO"} onClick={() => setMode("STILL")}><Camera/>Still</button><button className={mode === "VIDEO" ? "active" : ""} disabled={locked || dataset.permitted_capture_types === "STILL"} onClick={() => setMode("VIDEO")}><VideoIcon/>Video</button></div>
          <div className="field-pair"><label>Countdown<select disabled={locked} value={countdown} onChange={(event) => setCountdown(Number(event.target.value) as 3 | 5)}><option value={3}>3 seconds</option><option value={5}>5 seconds</option></select></label>{mode === "VIDEO" && <label>Duration<select disabled={locked} value={duration} onChange={(event) => setDuration(Number(event.target.value) as 0 | 5 | 10 | 15 | 30)}><option value={5}>5 seconds</option><option value={10}>10 seconds</option><option value={15}>15 seconds</option><option value={30}>30 seconds</option><option value={0}>Manual (max 2 min)</option></select></label>}</div>
          <details><summary>Advanced settings</summary><label>Camera<select disabled={locked} value={deviceId} onChange={(event) => setDeviceId(event.target.value)}><option value="">Default camera</option>{devices.map((device, index) => <option key={device.deviceId} value={device.deviceId}>{device.label || `Camera ${index + 1}`}</option>)}</select></label><label className="check"><input disabled={locked} type="checkbox" checked={mirror} onChange={(event) => setMirror(event.target.checked)}/> Mirror preview</label><label className="check"><input disabled={locked} type="checkbox" checked={skeleton} onChange={(event) => setSkeleton(event.target.checked)}/> Show skeleton overlay</label><label className="check"><input disabled={locked || !dataset.allow_raw_media} type="checkbox" checked={landmarksOnly || !dataset.allow_raw_media} onChange={(event) => setLandmarksOnly(event.target.checked)}/> Landmarks-only (no retained media)</label><div className="field-pair"><label>Next-sample rest<select value={restSeconds} onChange={(event) => setRestSeconds(Number(event.target.value))}><option value={0}>None</option><option value={3}>3 seconds</option><option value={5}>5 seconds</option></select></label><label>Collection target<input type="number" min={1} max={999} value={target} onChange={(event) => setTarget(Number(event.target.value))}/></label></div></details>
          {!review && captureState !== "RECORDING" && <button className="studio-capture" disabled={active || !labelId || !subjectId.trim()} onClick={triggerCapture}>{mode === "STILL" ? <Camera/> : <VideoIcon/>}{mode === "STILL" ? "Capture still" : "Start recording"}</button>}
          {captureState === "RECORDING" && <button className="studio-stop" onClick={() => stopRef.current?.(false)}><Square/>Stop and review</button>}
          {review && <div className="review-actions"><label>Review notes<textarea value={notes} onChange={(event) => setNotes(event.target.value)}/></label><div><button onClick={discard}><RotateCcw/>Retake</button><button onClick={discard}><Trash2/>Discard</button></div><button onClick={exportLocal}><Download/>Local export</button><button className="primary" disabled={captureState === "UPLOADING" || captureState === "VALIDATING"} onClick={() => void save(false)}>Save {uploadProgress ? `${uploadProgress}%` : ""}</button><button className="primary" disabled={captureState === "UPLOADING" || captureState === "VALIDATING"} onClick={() => void save(true)}>Save and capture next</button></div>}
          <div className="collection-target"><span>{savedCount} / {target} this session</span><progress value={savedCount} max={target}/></div>
        </>}
      </aside>
    </div>
    <section className="recent-samples"><h2>Recent samples</h2><div>{recent.map((sample) => <Link key={sample.sample_id} href={`/master/dataset/${sample.sample_id}`}><span className="sample-badge">{sample.sample_type}</span><strong>{sample.label_at_capture}</strong><small>{sample.subject_id} · {new Date(sample.created_at).toLocaleString()}</small></Link>)}{!recent.length && <p>No saved samples yet.</p>}</div></section>
  </section>;
}

function PoseOverlay({ observation, visible }: { observation: BrowserPoseObservation | null; visible: boolean }) {
  if (!visible || !observation?.normalizedLandmarks.length) return null;
  const points = observation.normalizedLandmarks; const links = [[11,12],[11,13],[13,15],[12,14],[14,16],[11,23],[12,24],[23,24]];
  return <svg className="browser-pose-overlay" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true">{links.map(([a,b]) => <line key={`${a}-${b}`} x1={points[a]?.x} y1={points[a]?.y} x2={points[b]?.x} y2={points[b]?.y}/>)}{points.filter((point) => [11,12,13,14,15,16,23,24].includes(point.index) && (point.visibility ?? 0) >= .45).map((point) => <circle key={point.index} cx={point.x} cy={point.y} r=".009"/>)}</svg>;
}
