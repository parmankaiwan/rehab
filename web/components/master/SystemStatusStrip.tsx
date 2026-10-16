"use client";

import Link from "next/link";
import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { masterApiGet } from "@/lib/masterApi";

type Cv = { cv_engine: boolean; camera_live: boolean; pose_receiving: boolean; storage_available: boolean; free_storage_bytes?: number; cv_fps?: number | null };
type Emg = { connection_state: string; serial_port?: string | null; baud_rate?: number | null; channels?: unknown[]; received_rate_hz?: number; latest_data_age_ms?: number | null; invalid_packets?: number; recorder_drops?: number };

export function SystemStatusStrip({ detailed = false }: { detailed?: boolean }) {
  const [cv, setCv] = useState<Cv | null>(null), [emg, setEmg] = useState<Emg | null>(null);
  const [loading, setLoading] = useState(true), [errors, setErrors] = useState({ cv: false, emg: false });
  const load = useCallback(async () => {
    setLoading(true);
    const [a, b] = await Promise.allSettled([masterApiGet<Cv>("/api/master/data/recordings/preflight", { retries: 1 }), masterApiGet<Emg>("/api/master/data/emg/status", { retries: 1 })]);
    if (a.status === "fulfilled") { setCv(a.value); setErrors((e) => ({ ...e, cv: false })); } else setErrors((e) => ({ ...e, cv: true }));
    if (b.status === "fulfilled") { setEmg(b.value); setErrors((e) => ({ ...e, emg: false })); } else setErrors((e) => ({ ...e, emg: true }));
    setLoading(false);
  }, []);
  useEffect(() => { void load(); const timer = setInterval(load, 5000); return () => clearInterval(timer); }, [load]);
  if (loading && !cv && !emg) return <div className="loading-skeleton system-loading" aria-label="Loading system status"><i/><i/><i/></div>;
  const items = [
    ["Main backend", !errors.cv && !!cv, errors.cv ? "STATUS UNAVAILABLE" : "ONLINE"],
    ["CV engine", !errors.cv && !!cv?.cv_engine, errors.cv ? "STATUS UNAVAILABLE" : cv?.cv_engine ? "LIVE" : "DISCONNECTED"],
    ["Camera", !errors.cv && !!cv?.camera_live, errors.cv ? "STATUS UNAVAILABLE" : cv?.camera_live ? "LIVE" : "DISCONNECTED"],
    ["EMG device", !errors.emg && emg?.connection_state === "STREAMING", errors.emg ? "STATUS UNAVAILABLE" : emg?.connection_state || "DISCONNECTED"],
    ["Dataset storage", !errors.cv && !!cv?.storage_available, errors.cv ? "STATUS UNAVAILABLE" : cv?.storage_available ? "READY" : "UNAVAILABLE"],
  ] as const;
  if (!detailed) return <div className="system-status">{items.map(([name, ok, label]) => <div key={name}><i className={ok ? "online" : "offline"}/><span>{name}</span><strong>{label}</strong></div>)}</div>;
  return <div><button className="system-refresh" onClick={load}><RefreshCw/>Refresh status</button><div className="system-sections">
    <section className="master-card"><h2>Application</h2><dl><div><dt>FastAPI</dt><dd>{errors.cv ? "Status unavailable" : cv ? "Online" : "Unavailable"}</dd></div><div><dt>Website</dt><dd>Online</dd></div></dl></section>
    <section className="master-card"><h2>Computer Vision</h2>{errors.cv ? <p className="master-alert">CV status unavailable. The device state is unknown.</p> : <dl><div><dt>Engine</dt><dd>{cv?.cv_engine ? "Live" : "Disconnected"}</dd></div><div><dt>Camera</dt><dd>{cv?.camera_live ? "Live" : "Disconnected"}</dd></div><div><dt>Pose stream</dt><dd>{cv?.pose_receiving ? "Receiving" : "Waiting"}</dd></div><div><dt>CV FPS</dt><dd>{cv?.cv_fps?.toFixed(1) || "Unavailable"}</dd></div></dl>}<Link href="/master/cv-data">Open CV</Link></section>
    <section className="master-card"><h2>EMG</h2>{errors.emg ? <p className="master-alert">EMG status unavailable. The physical device state is unknown.</p> : <dl><div><dt>Device</dt><dd>{emg?.connection_state || "Disconnected"}</dd></div><div><dt>Port</dt><dd>{emg?.serial_port || "Not connected"}</dd></div><div><dt>Baud</dt><dd>{emg?.baud_rate || "Unavailable"}</dd></div><div><dt>Channels</dt><dd>{emg?.channels?.length ?? "Unavailable"}</dd></div><div><dt>Sample rate</dt><dd>{emg?.received_rate_hz ? `${emg.received_rate_hz.toFixed(1)} Hz` : "Unavailable"}</dd></div><div><dt>Data age</dt><dd>{emg?.latest_data_age_ms != null ? `${emg.latest_data_age_ms.toFixed(1)} ms` : "Unavailable"}</dd></div><div><dt>Invalid packets</dt><dd>{emg?.invalid_packets ?? "Unavailable"}</dd></div><div><dt>Recorder drops</dt><dd>{emg?.recorder_drops ?? "Unavailable"}</dd></div></dl>}<Link href="/master/emg">Open EMG</Link></section>
    <section className="master-card"><h2>Storage</h2><dl><div><dt>Dataset</dt><dd>{errors.cv ? "Status unavailable" : cv?.storage_available ? "Ready" : "Unavailable"}</dd></div><div><dt>Free</dt><dd>{cv?.free_storage_bytes != null ? `${(cv.free_storage_bytes / 1073741824).toFixed(1)} GB` : "Unavailable"}</dd></div></dl></section>
  </div></div>;
}
