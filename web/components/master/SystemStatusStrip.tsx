"use client";

import Link from "next/link";
import { Power, RefreshCw, RotateCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { masterApiGet } from "@/lib/masterApi";

type Cv = { cv_engine: boolean; camera_live: boolean; pose_receiving: boolean; storage_available: boolean; free_storage_bytes?: number; cv_fps?: number | null };
type Emg = { connection_state: string; serial_port?: string | null; baud_rate?: number | null; channels?: unknown[]; received_rate_hz?: number; latest_data_age_ms?: number | null; invalid_packets?: number; recorder_drops?: number };
type Lifecycle = {
  deployment: "LOCAL_WINDOWS";
  application: string;
  backend: { ready: boolean; managed: boolean };
  frontend: { ready: boolean; managed: boolean };
  hardware_agent: { running: boolean; managed: boolean };
  cv: { process_running: boolean; camera_live: boolean; source: string; owner: string; error?: string | null };
  emg: { agent_running: boolean; board_connected: boolean; signal_live: boolean; state: string; port?: string | null; error?: string | null };
  supabase: { state: string };
  errors: string[];
  controls: { reconnect_cv: boolean; reconnect_emg: boolean; exit: boolean };
};

async function lifecycleAction(path: string) {
  const response = await fetch(`/api/master/data/lifecycle/${path}`, { method: "POST" });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || "Lifecycle action failed");
  return response.json();
}

export function SystemStatusStrip({ detailed = false }: { detailed?: boolean }) {
  const [cv, setCv] = useState<Cv | null>(null);
  const [emg, setEmg] = useState<Emg | null>(null);
  const [lifecycle, setLifecycle] = useState<Lifecycle | null>(null);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState("");
  const [message, setMessage] = useState("");
  const [errors, setErrors] = useState({ cv: false, emg: false });
  const load = useCallback(async () => {
    setLoading(true);
    const [a, b, c] = await Promise.allSettled([
      masterApiGet<Cv>("/api/master/data/recordings/preflight", { retries: 1 }),
      masterApiGet<Emg>("/api/master/data/emg/status", { retries: 1 }),
      masterApiGet<Lifecycle>("/api/master/data/lifecycle/status", { retries: 0, timeoutMs: 3000 }),
    ]);
    if (a.status === "fulfilled") { setCv(a.value); setErrors((value) => ({ ...value, cv: false })); } else setErrors((value) => ({ ...value, cv: true }));
    if (b.status === "fulfilled") { setEmg(b.value); setErrors((value) => ({ ...value, emg: false })); } else setErrors((value) => ({ ...value, emg: true }));
    setLifecycle(c.status === "fulfilled" ? c.value : null);
    setLoading(false);
  }, []);
  useEffect(() => { void load(); const timer = setInterval(load, 5000); return () => clearInterval(timer); }, [load]);

  async function runAction(target: "cv" | "emg") {
    setAction(target); setMessage("");
    try { await lifecycleAction(`reconnect/${target}`); setMessage(`${target.toUpperCase()} reconnect requested.`); setTimeout(() => void load(), 1000); }
    catch (cause) { setMessage(cause instanceof Error ? cause.message : "Reconnect failed"); }
    finally { setAction(""); }
  }
  async function exitFlexMap() {
    if (!confirm("Exit FlexMap and stop only the services started by the local launcher?")) return;
    setAction("exit"); setMessage("Stopping FlexMap. This page will disconnect safely.");
    try { await lifecycleAction("stop"); } catch (cause) { setMessage(cause instanceof Error ? cause.message : "Shutdown request failed"); setAction(""); }
  }

  if (loading && !cv && !emg) return <div className="loading-skeleton system-loading" aria-label="Loading system status"><i/><i/><i/></div>;
  const cvRunning = lifecycle ? lifecycle.cv.process_running && lifecycle.cv.camera_live : !errors.cv && !!cv?.cv_engine;
  const emgRunning = lifecycle ? lifecycle.emg.signal_live : !errors.emg && emg?.connection_state === "STREAMING";
  const items = [
    ["Main backend", lifecycle ? lifecycle.backend.ready : !errors.cv && !!cv, lifecycle ? lifecycle.backend.ready ? "CONNECTED" : "OFFLINE" : errors.cv ? "STATUS UNAVAILABLE" : "ONLINE"],
    ["CV engine", cvRunning, cvRunning ? "RUNNING" : "OFFLINE"],
    ["Camera", lifecycle ? lifecycle.cv.camera_live : !errors.cv && !!cv?.camera_live, lifecycle?.cv.camera_live || cv?.camera_live ? "CONNECTED" : "UNAVAILABLE"],
    ["EMG signal", emgRunning, emgRunning ? "LIVE" : lifecycle?.emg.state || emg?.connection_state || "DISCONNECTED"],
    ["Dataset storage", lifecycle?.supabase.state === "READY" || (!errors.cv && !!cv?.storage_available), lifecycle?.supabase.state || (cv?.storage_available ? "READY" : "UNAVAILABLE")],
  ] as const;
  if (!detailed) return <div className="system-status">{items.map(([name, ok, label]) => <div key={name}><i className={ok ? "online" : "offline"}/><span>{name}</span><strong>{label}</strong></div>)}</div>;
  return <div>
    <div className="review-actions horizontal">
      <button className="system-refresh" onClick={() => void load()}><RefreshCw/>Refresh status</button>
      <button disabled={!lifecycle?.controls.reconnect_cv || !!action} onClick={() => void runAction("cv")}><RotateCw/>Reconnect CV</button>
      <button disabled={!lifecycle?.controls.reconnect_emg || !!action} onClick={() => void runAction("emg")}><RotateCw/>Reconnect EMG</button>
      <button className="danger" disabled={!lifecycle?.controls.exit || !!action} onClick={() => void exitFlexMap()}><Power/>Exit FlexMap</button>
    </div>
    {message && <p role="status" className="master-alert">{message}</p>}
    {!lifecycle && <p className="master-alert">Hosted or independently started mode: local reconnect and shutdown controls are disabled.</p>}
    <div className="system-sections">
      <section className="master-card"><h2>Application</h2><dl><div><dt>Mode</dt><dd>{lifecycle ? "Local Windows application" : "Hosted / independent services"}</dd></div><div><dt>Lifecycle</dt><dd>{lifecycle?.application || "Not supervisor-managed"}</dd></div><div><dt>FastAPI</dt><dd>{lifecycle?.backend.ready || cv ? "Connected" : "Unavailable"}</dd></div><div><dt>Website</dt><dd>{lifecycle?.frontend.ready === false ? "Unavailable" : "Ready"}</dd></div></dl></section>
      <section className="master-card"><h2>Computer Vision</h2>{errors.cv ? <p className="master-alert">CV status unavailable. The device state is unknown.</p> : <dl><div><dt>Engine</dt><dd>{lifecycle?.cv.process_running || cv?.cv_engine ? "Running" : "Offline"}</dd></div><div><dt>Camera</dt><dd>{lifecycle?.cv.camera_live || cv?.camera_live ? "Connected" : "Unavailable"}</dd></div><div><dt>Owner</dt><dd>{lifecycle?.cv.owner || "External / browser selected"}</dd></div><div><dt>Pose stream</dt><dd>{cv?.pose_receiving ? "Receiving" : "Waiting"}</dd></div><div><dt>CV FPS</dt><dd>{cv?.cv_fps?.toFixed(1) || "Unavailable"}</dd></div></dl>}<Link href="/master/live/cv">Open CV Live</Link></section>
      <section className="master-card"><h2>EMG</h2>{errors.emg ? <p className="master-alert">EMG status unavailable. The physical device state is unknown.</p> : <dl><div><dt>Agent</dt><dd>{lifecycle?.hardware_agent.running ? "Running" : "Offline"}</dd></div><div><dt>Board</dt><dd>{lifecycle?.emg.board_connected ? "Connected" : "Disconnected"}</dd></div><div><dt>Signal</dt><dd>{lifecycle?.emg.signal_live ? "Live" : "No signal"}</dd></div><div><dt>Port</dt><dd>{lifecycle?.emg.port || emg?.serial_port || "Not connected"}</dd></div><div><dt>Sample rate</dt><dd>{emg?.received_rate_hz ? `${emg.received_rate_hz.toFixed(1)} Hz` : "Unavailable"}</dd></div><div><dt>Data age</dt><dd>{emg?.latest_data_age_ms != null ? `${emg.latest_data_age_ms.toFixed(1)} ms` : "Unavailable"}</dd></div></dl>}<Link href="/master/live/emg">Open EMG Live</Link></section>
      <section className="master-card"><h2>Storage</h2><dl><div><dt>Supabase</dt><dd>{lifecycle?.supabase.state || "Status through data service"}</dd></div><div><dt>Local recording space</dt><dd>{cv?.storage_available ? "Ready" : "Unavailable"}</dd></div><div><dt>Free</dt><dd>{cv?.free_storage_bytes != null ? `${(cv.free_storage_bytes / 1073741824).toFixed(1)} GB` : "Unavailable"}</dd></div></dl></section>
    </div>
  </div>;
}
