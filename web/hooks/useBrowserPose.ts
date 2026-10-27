"use client";

import { RefObject, useCallback, useEffect, useRef, useState } from "react";
import type { NormalizedLandmark, PoseLandmarker, PoseLandmarkerResult } from "@mediapipe/tasks-vision";
import type { DisplayLandmark, PostureComponent, PostureSnapshot, PostureState } from "@/types/posture";

export type BrowserPoseState = "STARTING" | "CAMERA_READY" | "LIVE" | "DENIED" | "UNAVAILABLE";
export type BrowserPoseDelegate = "GPU" | "CPU";

export function browserCameraErrorMessage(cause: unknown): string {
  if (cause instanceof DOMException) {
    if (["NotAllowedError", "SecurityError"].includes(cause.name)) {
      return "Camera permission was not granted. Allow Camera in this site's browser controls, then check Windows Settings > Privacy & security > Camera > Let desktop apps access your camera. Click Reconnect after allowing access.";
    }
    if (["NotReadableError", "AbortError"].includes(cause.name)) {
      return "The camera could not be opened. Close other camera apps, FlexMap camera tabs, and the Python CV viewer, then click Reconnect.";
    }
    if (cause.name === "NotFoundError") return "No camera was found. Connect or enable a camera, check its privacy shutter, then click Reconnect.";
    if (cause.name === "OverconstrainedError") return "The selected camera is unavailable or does not support the requested settings. Reconnect the camera or select another device.";
  }
  return cause instanceof Error ? cause.message : "Browser camera could not start.";
}

export interface RawPoseLandmark {
  index: number;
  name: string;
  x: number;
  y: number;
  z: number;
  visibility: number | null;
  presence: number | null;
}

export interface BrowserPoseObservation {
  poseResultSequenceId: number;
  inferenceIterationId: number;
  sourceFrameObservationId: number;
  wallClockTimestampMs: number;
  monotonicTimestampMs: number;
  mediaTimestampMs: number;
  inferenceDurationMs: number;
  valid: boolean;
  normalizedLandmarks: RawPoseLandmark[];
  worldLandmarks: RawPoseLandmark[] | null;
  snapshot: PostureSnapshot | null;
  model: {
    packageVersion: string;
    modelUrl: string;
    wasmUrl: string;
    delegate: BrowserPoseDelegate;
    runningMode: "VIDEO";
  };
}

export interface BrowserStillCapture {
  image: Blob;
  observation: BrowserPoseObservation;
  width: number;
  height: number;
  mediaTimestampMs: number;
  orientation: "LANDSCAPE" | "PORTRAIT" | "SQUARE";
}

const PACKAGE_VERSION = "1.1.1";
const WASM_ROOT = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${PACKAGE_VERSION}/wasm`;
const MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task";
const LANDMARK_NAMES = ["NOSE", "LEFT_EYE_INNER", "LEFT_EYE", "LEFT_EYE_OUTER", "RIGHT_EYE_INNER", "RIGHT_EYE", "RIGHT_EYE_OUTER", "LEFT_EAR", "RIGHT_EAR", "MOUTH_LEFT", "MOUTH_RIGHT", "LEFT_SHOULDER", "RIGHT_SHOULDER", "LEFT_ELBOW", "RIGHT_ELBOW", "LEFT_WRIST", "RIGHT_WRIST", "LEFT_PINKY", "RIGHT_PINKY", "LEFT_INDEX", "RIGHT_INDEX", "LEFT_THUMB", "RIGHT_THUMB", "LEFT_HIP", "RIGHT_HIP", "LEFT_KNEE", "RIGHT_KNEE", "LEFT_ANKLE", "RIGHT_ANKLE", "LEFT_HEEL", "RIGHT_HEEL", "LEFT_FOOT_INDEX", "RIGHT_FOOT_INDEX"];
const DISPLAY_NAMES: Record<number, string> = { 0: "HEAD_CENTER", 11: "LEFT_SHOULDER", 12: "RIGHT_SHOULDER", 13: "LEFT_ELBOW", 14: "RIGHT_ELBOW", 15: "LEFT_WRIST", 16: "RIGHT_WRIST", 23: "LEFT_HIP", 24: "RIGHT_HIP" };
const REQUIRED = Object.values(DISPLAY_NAMES);

function component(state: PostureState, display_name: string, value?: number): PostureComponent {
  return { state, display_name, value, units: value == null ? undefined : "normalized" };
}

export function browserSnapshotFromLandmarks(points: NormalizedLandmark[], frame: number, fps: number): PostureSnapshot {
  const landmarks: Record<string, DisplayLandmark> = {};
  for (const [rawIndex, name] of Object.entries(DISPLAY_NAMES)) {
    const point = points[Number(rawIndex)];
    const visibility = point?.visibility ?? 0;
    landmarks[name] = { x: point?.x ?? 0, y: point?.y ?? 0, z: point?.z, visibility, presence: point?.presence, valid: !!point && visibility >= .45 };
  }
  const validCount = REQUIRED.filter((name) => landmarks[name]?.valid).length;
  const shouldersVisible = landmarks.LEFT_SHOULDER.valid && landmarks.RIGHT_SHOULDER.valid;
  const hipsVisible = landmarks.LEFT_HIP.valid && landmarks.RIGHT_HIP.valid;
  const leftArmVisible = ["LEFT_SHOULDER", "LEFT_ELBOW", "LEFT_WRIST"].every((name) => landmarks[name].valid);
  const rightArmVisible = ["RIGHT_SHOULDER", "RIGHT_ELBOW", "RIGHT_WRIST"].every((name) => landmarks[name].valid);
  const shoulderWidth = shouldersVisible ? Math.max(.001, Math.abs(landmarks.LEFT_SHOULDER.x - landmarks.RIGHT_SHOULDER.x)) : 1;
  const shoulderLevel = shouldersVisible ? Math.abs(landmarks.LEFT_SHOULDER.y - landmarks.RIGHT_SHOULDER.y) / shoulderWidth : 1;
  const shoulderCenter = shouldersVisible ? (landmarks.LEFT_SHOULDER.x + landmarks.RIGHT_SHOULDER.x) / 2 : 0;
  const hipCenter = hipsVisible ? (landmarks.LEFT_HIP.x + landmarks.RIGHT_HIP.x) / 2 : 1;
  const trunkCenter = shouldersVisible && hipsVisible ? Math.abs(shoulderCenter - hipCenter) / shoulderWidth : 1;
  const visibilityReady = validCount === REQUIRED.length;
  const alignmentReady = shoulderLevel <= .18 && trunkCenter <= .18;
  const progress = Math.min(1, (validCount / REQUIRED.length) * .75 + (shoulderLevel <= .28 ? .125 : 0) + (trunkCenter <= .28 ? .125 : 0));
  const ready = visibilityReady && alignmentReady;
  const tracking_quality = validCount >= REQUIRED.length - 1 ? "GOOD" : validCount >= 5 ? "POOR" : "LOST";
  const overall_state: PostureState = tracking_quality === "LOST" ? "GREY" : ready ? "GREEN" : progress >= .75 ? "ORANGE" : "RED";
  const feedback: string[] = [];
  if (!visibilityReady) feedback.push("Keep your head, shoulders, arms, and hips visible.");
  if (visibilityReady && shoulderLevel > .18) feedback.push("Relax your shoulders into a comfortable level position.");
  if (visibilityReady && trunkCenter > .18) feedback.push("Bring your upper body gently toward the center.");
  const components: Record<string, PostureComponent> = {
    BODY_TRACKING_COMPLETE: component(visibilityReady ? "GREEN" : "GREY", "Body tracking"),
    LEFT_ARM_VISIBLE: component(leftArmVisible ? "GREEN" : "GREY", "Left arm visible"),
    RIGHT_ARM_VISIBLE: component(rightArmVisible ? "GREEN" : "GREY", "Right arm visible"),
    LEFT_HIP_VISIBLE: component(landmarks.LEFT_HIP.valid ? "GREEN" : "GREY", "Left hip visible"),
    RIGHT_HIP_VISIBLE: component(landmarks.RIGHT_HIP.valid ? "GREEN" : "GREY", "Right hip visible"),
    SHOULDER_LEVEL: component(shoulderLevel <= .18 ? "GREEN" : shoulderLevel <= .28 ? "ORANGE" : "RED", "Shoulder level", shoulderLevel),
    TRUNK_CENTER: component(trunkCenter <= .18 ? "GREEN" : trunkCenter <= .28 ? "ORANGE" : "RED", "Trunk center", trunkCenter),
  };
  return {
    timestamp: Date.now() / 1000, capture_frame_id: frame, connected: true, tracking_quality,
    overall_state, ready, ready_progress: progress, ready_confidence: progress,
    baseline_captured: false, ready_stage: ready ? "READY" : tracking_quality === "LOST" ? "TRACKING_INCOMPLETE" : progress >= .75 ? "ALMOST_READY" : "SEARCHING",
    landmarks, components, feedback: feedback.slice(0, 2), fps,
  };
}

function rawLandmarks(points: NormalizedLandmark[] | undefined): RawPoseLandmark[] | null {
  if (!points?.length) return null;
  return points.map((point, index) => ({ index, name: LANDMARK_NAMES[index] || `LANDMARK_${index}`, x: point.x, y: point.y, z: point.z, visibility: point.visibility ?? null, presence: point.presence ?? null }));
}

function canvasBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("Could not encode the camera frame.")), "image/jpeg", .92));
}

export function useBrowserPose(enabled = true, deviceId?: string): {
  videoRef: RefObject<HTMLVideoElement | null>;
  snapshot: PostureSnapshot | null;
  state: BrowserPoseState;
  error: string;
  delegate: BrowserPoseDelegate | null;
  inferenceCount: number;
  restart: () => void;
  getStream: () => MediaStream | null;
  getLatestObservation: () => BrowserPoseObservation | null;
  subscribe: (listener: (observation: BrowserPoseObservation) => void) => () => void;
  captureStill: () => Promise<BrowserStillCapture>;
} {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const landmarkerRef = useRef<PoseLandmarker | null>(null);
  const delegateRef = useRef<BrowserPoseDelegate | null>(null);
  const latestRef = useRef<BrowserPoseObservation | null>(null);
  const listenersRef = useRef(new Set<(observation: BrowserPoseObservation) => void>());
  const sequenceRef = useRef(0);
  const inferenceIterationRef = useRef(0);
  const sourceFrameRef = useRef(0);
  const lastInferenceTimestampRef = useRef(0);
  const [snapshot, setSnapshot] = useState<PostureSnapshot | null>(null);
  const [state, setState] = useState<BrowserPoseState>("STARTING");
  const [error, setError] = useState("");
  const [delegate, setDelegate] = useState<BrowserPoseDelegate | null>(null);
  const [inferenceCount, setInferenceCount] = useState(0);
  const [generation, setGeneration] = useState(0);
  const [cameraLeaseReady, setCameraLeaseReady] = useState(false);
  const cameraLeaseIdRef = useRef("");
  const restart = useCallback(() => setGeneration((value) => value + 1), []);
  const getStream = useCallback(() => streamRef.current, []);
  const getLatestObservation = useCallback(() => latestRef.current, []);
  const subscribe = useCallback((listener: (observation: BrowserPoseObservation) => void) => {
    listenersRef.current.add(listener);
    return () => listenersRef.current.delete(listener);
  }, []);

  const buildObservation = useCallback((result: PoseLandmarkerResult, mediaTimestampMs: number, startedAt: number, fps: number): BrowserPoseObservation => {
    sequenceRef.current += 1;
    inferenceIterationRef.current += 1;
    const normalized = result.landmarks[0];
    const snapshotValue = normalized ? browserSnapshotFromLandmarks(normalized, inferenceIterationRef.current, fps) : null;
    return {
      poseResultSequenceId: sequenceRef.current,
      inferenceIterationId: inferenceIterationRef.current,
      sourceFrameObservationId: sourceFrameRef.current,
      wallClockTimestampMs: Date.now(),
      monotonicTimestampMs: startedAt,
      mediaTimestampMs,
      inferenceDurationMs: performance.now() - startedAt,
      valid: !!normalized,
      normalizedLandmarks: rawLandmarks(normalized) || [],
      worldLandmarks: rawLandmarks(result.worldLandmarks[0]),
      snapshot: snapshotValue,
      model: { packageVersion: PACKAGE_VERSION, modelUrl: MODEL_URL, wasmUrl: WASM_ROOT, delegate: delegateRef.current || "CPU", runningMode: "VIDEO" },
    };
  }, []);

  const captureStill = useCallback(async (): Promise<BrowserStillCapture> => {
    const video = videoRef.current;
    const landmarker = landmarkerRef.current;
    if (!video || !landmarker || video.readyState < 2) throw new Error("Camera and pose model must be ready before capture.");
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) throw new Error("Camera frame capture is unavailable.");
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const startedAt = Math.max(performance.now(), lastInferenceTimestampRef.current + .01);
    lastInferenceTimestampRef.current = startedAt;
    sourceFrameRef.current += 1;
    const result = landmarker.detectForVideo(canvas, startedAt);
    const observation = buildObservation(result, video.currentTime * 1000, startedAt, latestRef.current?.snapshot?.fps || 0);
    if (!observation.valid) throw new Error("No pose result was available for the captured frame.");
    return { image: await canvasBlob(canvas), observation, width: canvas.width, height: canvas.height, mediaTimestampMs: video.currentTime * 1000, orientation: canvas.width === canvas.height ? "SQUARE" : canvas.width > canvas.height ? "LANDSCAPE" : "PORTRAIT" };
  }, [buildObservation]);

  useEffect(() => {
    if (!enabled) { setCameraLeaseReady(false); return; }
    let active = true;
    let heartbeat: ReturnType<typeof setInterval> | undefined;
    const leaseId = cameraLeaseIdRef.current || crypto.randomUUID();
    cameraLeaseIdRef.current = leaseId;
    const send = async (action: "acquire" | "renew" | "release") => {
      const response = await fetch("/api/local-camera-lease", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ lease_id: leaseId, action }), keepalive: action === "release",
      });
      if (response.status === 409) return { accepted: true, mode: "HOSTED" };
      return response.json();
    };
    void send("acquire").then((result) => {
      if (!active) return;
      if (!result.accepted) { setState("UNAVAILABLE"); setError(result.message || "Camera is already in use by another FlexMap page."); return; }
      // Give the Python owner a bounded moment to release VideoCapture.
      window.setTimeout(() => active && setCameraLeaseReady(true), result.mode === "HOSTED" ? 0 : 400);
      heartbeat = setInterval(() => void send("renew").catch(() => undefined), 2000);
    }).catch(() => { if (active) setCameraLeaseReady(true); });
    return () => {
      active = false;
      setCameraLeaseReady(false);
      if (heartbeat) clearInterval(heartbeat);
      void send("release").catch(() => undefined);
    };
  }, [enabled, generation]);

  useEffect(() => {
    if (!enabled || !cameraLeaseReady) return;
    let stopped = false;
    let animation = 0;
    let videoFrameCallback = 0;
    let fpsFrames = 0;
    let fpsStarted = performance.now();
    let lastFallbackMediaTime = -1;
    let lastReactUpdate = 0;
    const mountedVideo = videoRef.current;
    let ownedStream: MediaStream | null = null;
    let ownedLandmarker: PoseLandmarker | null = null;
    const releaseResources = () => {
      if (ownedLandmarker) {
        ownedLandmarker.close();
        if (landmarkerRef.current === ownedLandmarker) landmarkerRef.current = null;
        ownedLandmarker = null;
      }
      if (ownedStream) {
        ownedStream.getTracks().forEach((track) => track.stop());
        if (streamRef.current === ownedStream) streamRef.current = null;
        if (mountedVideo?.srcObject === ownedStream) mountedVideo.srcObject = null;
        ownedStream = null;
      }
    };
    setState("STARTING"); setError(""); setSnapshot(null); setDelegate(null); setInferenceCount(0);

    const publish = (observation: BrowserPoseObservation, now: number) => {
      latestRef.current = observation;
      listenersRef.current.forEach((listener) => listener(observation));
      if (now - lastReactUpdate >= 100) {
        lastReactUpdate = now;
        setSnapshot(observation.snapshot);
        setInferenceCount(observation.inferenceIterationId);
        setState(observation.valid ? "LIVE" : "CAMERA_READY");
      }
    };

    const infer = (mediaTimestampMs: number) => {
      const video = videoRef.current;
      const landmarker = landmarkerRef.current;
      if (stopped || !video || !landmarker || video.readyState < 2) return;
      const startedAt = Math.max(performance.now(), lastInferenceTimestampRef.current + .01);
      if (startedAt - lastInferenceTimestampRef.current < 45) return;
      lastInferenceTimestampRef.current = startedAt;
      sourceFrameRef.current += 1;
      fpsFrames += 1;
      const result = landmarker.detectForVideo(video, startedAt);
      const fps = fpsFrames * 1000 / Math.max(1, startedAt - fpsStarted);
      publish(buildObservation(result, mediaTimestampMs, startedAt, fps), startedAt);
      if (fpsFrames >= 120) { fpsFrames = 0; fpsStarted = startedAt; }
    };

    const run = async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error("This browser does not support camera access.");
        const stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { deviceId: deviceId ? { exact: deviceId } : undefined, facingMode: deviceId ? undefined : "user", width: { ideal: 1280 }, height: { ideal: 720 } } });
        if (stopped) { stream.getTracks().forEach((track) => track.stop()); return; }
        ownedStream = stream;
        streamRef.current = stream;
        const video = mountedVideo;
        if (!video) throw new Error("Camera display is not ready.");
        video.srcObject = stream;
        await video.play();
        setState("CAMERA_READY");
        const { FilesetResolver, PoseLandmarker } = await import("@mediapipe/tasks-vision");
        const vision = await FilesetResolver.forVisionTasks(WASM_ROOT);
        if (stopped) return;
        try {
          ownedLandmarker = await PoseLandmarker.createFromOptions(vision, { baseOptions: { modelAssetPath: MODEL_URL, delegate: "GPU" }, runningMode: "VIDEO", numPoses: 1, minPoseDetectionConfidence: .5, minPosePresenceConfidence: .5, minTrackingConfidence: .5 });
          delegateRef.current = "GPU";
        } catch {
          if (stopped) return;
          ownedLandmarker = await PoseLandmarker.createFromOptions(vision, { baseOptions: { modelAssetPath: MODEL_URL, delegate: "CPU" }, runningMode: "VIDEO", numPoses: 1, minPoseDetectionConfidence: .5, minPosePresenceConfidence: .5, minTrackingConfidence: .5 });
          delegateRef.current = "CPU";
        }
        if (stopped) { releaseResources(); return; }
        landmarkerRef.current = ownedLandmarker;
        setDelegate(delegateRef.current);
        const supportsFrameCallback = "requestVideoFrameCallback" in video;
        if (supportsFrameCallback) {
          const onFrame = (_now: number, metadata: VideoFrameCallbackMetadata) => {
            if (stopped) return;
            infer(metadata.mediaTime * 1000);
            videoFrameCallback = video.requestVideoFrameCallback(onFrame);
          };
          videoFrameCallback = video.requestVideoFrameCallback(onFrame);
        } else {
          const fallbackVideo: HTMLVideoElement = video;
          const onAnimation = () => {
            if (stopped) return;
            if (fallbackVideo.currentTime !== lastFallbackMediaTime) {
              lastFallbackMediaTime = fallbackVideo.currentTime;
              infer(fallbackVideo.currentTime * 1000);
            }
            animation = requestAnimationFrame(onAnimation);
          };
          animation = requestAnimationFrame(onAnimation);
        }
      } catch (cause) {
        releaseResources();
        if (stopped) return;
        const denied = cause instanceof DOMException && ["NotAllowedError", "SecurityError"].includes(cause.name);
        setState(denied ? "DENIED" : "UNAVAILABLE");
        setError(browserCameraErrorMessage(cause));
      }
    };
    void run();
    return () => {
      stopped = true;
      cancelAnimationFrame(animation);
      const video = mountedVideo;
      if (video && videoFrameCallback && "cancelVideoFrameCallback" in video) video.cancelVideoFrameCallback(videoFrameCallback);
      releaseResources();
      latestRef.current = null;
    };
  }, [enabled, cameraLeaseReady, generation, deviceId, buildObservation]);

  return { videoRef, snapshot, state, error, delegate, inferenceCount, restart, getStream, getLatestObservation, subscribe, captureStill };
}
