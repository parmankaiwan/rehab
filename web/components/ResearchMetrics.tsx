"use client";

import { useEffect, useState } from "react";
import { PostureSnapshot } from "@/types/posture";

interface VideoMetrics {
  transport: string;
  frame_sequence: number | null;
  backend_frame_age_ms: number | null;
  source_frame_age_ms: number | null;
  jpeg_encode_ms: number | null;
  frame_receive_fps: number | null;
  webrtc_clients: number;
  effective_queue_depth: number;
}

const format = (value: number | null | undefined, suffix = "") => value == null ? "—" : `${value.toFixed(1)}${suffix}`;

export function ResearchMetrics({ snapshot, stale }: { snapshot: PostureSnapshot | null; stale: boolean }) {
  const [metrics, setMetrics] = useState<VideoMetrics | null>(null);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    let active = true;
    const update = async () => {
      try {
        const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}/api/video/metrics`, { cache: "no-store" });
        if (response.ok && active) setMetrics(await response.json() as VideoMetrics);
      } catch { /* availability is already represented by empty metrics */ }
      if (active) setNow(Date.now());
    };
    void update();
    const timer = setInterval(() => void update(), 1000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  const dataAge = snapshot ? now - snapshot.timestamp * 1000 : null;
  const items = [
    ["CV FPS", format(snapshot?.fps)], ["Pose rate", format(snapshot?.fps, " Hz")],
    ["Hand target", snapshot?.fps ? format(snapshot.fps / 2, " Hz") : "—"],
    ["Frame receive", format(metrics?.frame_receive_fps, " FPS")], ["JPEG encode", format(metrics?.jpeg_encode_ms, " ms")],
    ["Source age", format(metrics?.source_frame_age_ms, " ms")], ["Backend age", format(metrics?.backend_frame_age_ms, " ms")],
    ["WebSocket age", format(dataAge, " ms")], ["Frame sequence", metrics?.frame_sequence?.toString() ?? "—"],
    ["WebRTC clients", metrics?.webrtc_clients?.toString() ?? "0"], ["Video queue", metrics?.effective_queue_depth?.toString() ?? "0"],
    ["Data", stale ? "STALE" : "CURRENT"],
  ];
  return <section className="debug-panel"><span>Research performance</span><dl>{items.map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl></section>;
}
