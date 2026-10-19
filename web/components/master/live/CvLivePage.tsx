"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { LiveCameraView } from "@/components/LiveCameraView";
import { useBrowserPose } from "@/hooks/useBrowserPose";
import { usePostureStream } from "@/hooks/usePostureStream";
import { selectCoach } from "@/lib/bodyRegionMap";
import type { PostureComponent, PostureSnapshot } from "@/types/posture";
import { LiveStatusBadge, type LiveState } from "./LiveStatusBadge";

type CvSource = "BROWSER" | "ENGINE";

const title = (value: string) => value.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (character) => character.toUpperCase());
const measurementKeys = ["LEFT_ELBOW_ANGLE", "RIGHT_ELBOW_ANGLE", "LEFT_WRIST_SPEED", "RIGHT_WRIST_SPEED", "TRUNK_ANGLE", "TRUNK_CENTER_OFFSET", "SHOULDER_DIFFERENCE"];

export function CvLivePage() {
  const [source, setSource] = useState<CvSource>("ENGINE");
  const browser = useBrowserPose(source === "BROWSER");
  const engine = usePostureStream(source === "ENGINE");
  const snapshot = source === "BROWSER" ? browser.snapshot : engine.snapshot;
  const coach = useMemo(() => selectCoach(snapshot), [snapshot]);
  const engineState: LiveState = engine.connectionState === "ERROR"
    ? "ERROR"
    : engine.connectionState !== "CONNECTED"
      ? engine.connectionState
      : engine.isStale
        ? "STALE"
        : engine.snapshot
          ? "LIVE"
          : "CONNECTING";
  const browserState: LiveState = browser.state === "DENIED" || browser.state === "UNAVAILABLE"
    ? "ERROR"
    : browser.state === "LIVE" && browser.snapshot
      ? "LIVE"
      : "CONNECTING";
  const state = source === "BROWSER" ? browserState : engineState;
  const components = Object.entries(snapshot?.components || {});
  const measurements = components.filter(([key, value]) => measurementKeys.includes(key) && value.value != null);
  const age = snapshot ? Math.max(0, Date.now() - snapshot.timestamp * 1000) : null;
  const reconnect = source === "BROWSER" ? browser.restart : engine.reconnect;

  return <section>
    <div className="live-page-title">
      <div>
        <nav className="breadcrumbs"><Link href="/master/live">Live Sensors</Link><span>›</span><strong>CV Live</strong></nav>
        <span className="eyebrow">Live monitoring only · no recording</span>
        <h1>Computer Vision Live</h1>
      </div>
      <div className="camera-actions">
        <div className="transport-switch" aria-label="CV source">
          <button className={source === "BROWSER" ? "active" : ""} onClick={() => setSource("BROWSER")}>Browser MediaPipe</button>
          <button className={source === "ENGINE" ? "active" : ""} onClick={() => setSource("ENGINE")}>FlexMap Engine</button>
        </div>
        <LiveStatusBadge state={state}/>
      </div>
    </div>

    {state !== "LIVE" && <div className="live-warning">
      <strong>{state === "STALE" ? "Camera stream stale" : source === "BROWSER" ? "Browser camera unavailable" : "CV connection unavailable"}</strong>
      <span>{state === "STALE"
        ? "The last sensor snapshot is no longer current."
        : source === "BROWSER"
          ? browser.error || "Allow camera access in this browser and keep your upper body in view."
          : "Start the backend and FlexMap CV engine, then reconnect."}</span>
      <button onClick={reconnect}>Reconnect</button>
    </div>}

    <div className="cv-live-grid">
      <LiveCameraView
        snapshot={snapshot}
        unavailable={state === "ERROR"}
        research
        activeRegion={coach.region}
        highlightState={coach.state}
        coachPrimary={coach.primary}
        mirrored={source === "BROWSER"}
        browserVideoRef={source === "BROWSER" ? browser.videoRef : undefined}
        browserState={source === "BROWSER" ? browser.state : undefined}
      />
      <aside className="live-diagnostics">
        <CvSystem source={source} state={state} snapshot={snapshot} age={age} socket={source === "BROWSER" ? "NOT REQUIRED" : engine.connectionState}/>
        <ReadyMonitor snapshot={snapshot} stage={coach.stage} instruction={coach.primary}/>
      </aside>
    </div>

    <CvDetails components={components} measurements={measurements} source={source}/>
    <p className="live-monitor-note">Opening this viewer does not create a CV recording, research session, label, or Dataset artifact.</p>
  </section>;
}

function CvSystem({ source, state, snapshot, age, socket }: { source: CvSource; state: LiveState; snapshot: PostureSnapshot | null; age: number | null; socket: string }) {
  const performance = snapshot?.exercise_snapshot?.performance;
  const scheduler = performance?.pose_scheduler;
  const fmt = (value?: number | null, suffix = " ms") => value == null ? "Unavailable" : value.toFixed(1) + suffix;
  return <article className="master-card">
    <div className="master-card-head"><strong>System</strong><LiveStatusBadge state={state}/></div>
    <dl className="live-metric-list">
      <div><dt>Source</dt><dd>{source === "BROWSER" ? "BROWSER MEDIAPIPE" : "FLEXMAP ENGINE"}</dd></div>
      <div><dt>CV engine</dt><dd>{snapshot?.connected && state === "LIVE" ? "LIVE" : "WAITING"}</dd></div>
      <div><dt>Pose tracking</dt><dd>{snapshot?.tracking_quality || "Waiting"}</dd></div>
      <div><dt>Overall posture</dt><dd>{snapshot?.overall_state || "Waiting"}</dd></div>
      <div><dt>Camera</dt><dd>{snapshot?.fps != null ? snapshot.fps.toFixed(1) + " FPS" : "Not available"}</dd></div>
      {source === "ENGINE" && <>
        <div><dt>Pose results</dt><dd>{fmt(scheduler?.pose_result_hz, " Hz")}</dd></div>
        <div><dt>Pose latency p95</dt><dd>{fmt(scheduler?.pose_latency_p95_ms)}</dd></div>
        <div><dt>Pose data age p95</dt><dd>{fmt(performance?.pose_result_age?.p95_ms)}</dd></div>
        <div><dt>Pose queue</dt><dd>{scheduler?.buffer_depth ?? "Unavailable"} / 1</dd></div>
        <div><dt>Busy frames skipped</dt><dd>{scheduler?.pose_skipped_busy ?? "Unavailable"}</dd></div>
        <div><dt>Drawing mean</dt><dd>{fmt(performance?.drawing?.mean_ms)}</dd></div>
      </>}
      <div><dt>Latest data age</dt><dd>{age != null ? Math.round(age) + " ms" : "Waiting"}</dd></div>
      <div><dt>WebSocket</dt><dd>{socket}</dd></div>
    </dl>
    <small>{source === "BROWSER" ? "MediaPipe Pose Landmarker · on-device browser inference" : `${snapshot?.exercise_snapshot?.cv_pipeline_version || "Pipeline version unavailable"} · ${snapshot?.exercise_snapshot?.performance_profile || "Profile unavailable"}`}</small>
  </article>;
}

function ReadyMonitor({ snapshot, stage, instruction }: { snapshot: PostureSnapshot | null; stage: string; instruction: string }) {
  return <article className="master-card ready-live">
    <span className="eyebrow">Ready status</span>
    <h2>{snapshot?.ready ? "READY" : stage.replaceAll("_", " ")}</h2>
    <strong>{snapshot ? Math.round(snapshot.ready_progress * 100) + "%" : "--"}</strong>
    <progress max="1" value={snapshot?.ready_progress || 0}/>
    <p>{instruction}</p>
  </article>;
}

function CvDetails({ components, measurements, source }: { components: [string, PostureComponent][]; measurements: [string, PostureComponent][]; source: CvSource }) {
  return <div className="live-detail-grid">
    <article className="master-card">
      <h2>Ready details</h2>
      {components.length
        ? <div className="live-component-grid">{components.map(([key, value]) => <div key={key}><span>{value.display_name || title(key)}</span><strong className={"state-" + value.state.toLowerCase()}>{value.state}</strong></div>)}</div>
        : <p>Waiting for posture components.</p>}
    </article>
    <article className="master-card">
      <h2>Live measurements</h2>
      {measurements.length
        ? <dl className="live-metric-list">{measurements.map(([key, value]) => <div key={key}><dt>{value.display_name || title(key)}</dt><dd>{value.value?.toFixed(1)} {value.units || ""}</dd></div>)}</dl>
        : <p>Measurements are not available in the current snapshot.</p>}
      <details>
        <summary>Technical details</summary>
        <p>{source === "BROWSER"
          ? "Camera frames and MediaPipe pose inference stay in this browser. This live view does not feed the research recording engine."
          : `Video uses the existing ${String(process.env.NEXT_PUBLIC_VIDEO_TRANSPORT || "WEBRTC").toUpperCase()} transport and the FlexMap backend pose engine.`}</p>
      </details>
    </article>
  </div>;
}
