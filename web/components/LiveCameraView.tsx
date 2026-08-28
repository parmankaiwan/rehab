"use client";

import { Expand, Minimize2, Radio, VideoOff } from "lucide-react";
import { memo, useEffect, useState } from "react";
import { useWebRTCVideo } from "@/hooks/useWebRTCVideo";
import { BodyRegion } from "@/lib/bodyRegionMap";
import { PostureSnapshot, PostureState } from "@/types/posture";
import { CameraBodyOverlay } from "./CameraBodyOverlay";

export type VideoTransport = "WEBRTC" | "MJPEG";

export const LiveCameraView = memo(function LiveCameraView({ snapshot, unavailable, research, activeRegion, highlightState, mirrored = false, coachPrimary }: { snapshot: PostureSnapshot | null; unavailable: boolean; research: boolean; activeRegion?: BodyRegion | null; highlightState?: PostureState; mirrored?: boolean; coachPrimary?: string }) {
  const configured = (process.env.NEXT_PUBLIC_VIDEO_TRANSPORT ?? "WEBRTC").toUpperCase();
  const [transport, setTransport] = useState<VideoTransport>(configured === "MJPEG" ? "MJPEG" : "WEBRTC");
  const [full, setFull] = useState(false);
  const [mjpegFailed, setMjpegFailed] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const webrtc = useWebRTCVideo(transport === "WEBRTC" && !unavailable);
  const mjpegUrl = process.env.NEXT_PUBLIC_VIDEO_URL ?? "http://localhost:8000/video-feed";

  useEffect(() => {
    if (!mjpegFailed) return;
    const timer = setTimeout(() => { setRetryKey((key) => key + 1); setMjpegFailed(false); }, 2000);
    return () => clearTimeout(timer);
  }, [mjpegFailed]);

  const videoUnavailable = unavailable || (transport === "WEBRTC" ? webrtc.state === "UNAVAILABLE" : mjpegFailed);
  return <section className={`camera-card camera-state-${(snapshot?.overall_state ?? "GREY").toLowerCase()} ${full ? "camera-card--full" : ""}`} aria-label="Live posture view">
    <div className="card-heading">
      <div><span className="eyebrow">Live posture view</span><h2>Camera</h2></div>
      <div className="camera-actions">
        {research && <div className="transport-switch" aria-label="Video transport">
          <button className={transport === "WEBRTC" ? "active" : ""} onClick={() => setTransport("WEBRTC")}>WebRTC</button>
          <button className={transport === "MJPEG" ? "active" : ""} onClick={() => setTransport("MJPEG")}>MJPEG</button>
        </div>}
        <button className="text-button" onClick={() => setFull(!full)}>{full ? <Minimize2 size={16}/> : <Expand size={16}/>} {full ? "Exit" : "Fullscreen"}</button>
      </div>
    </div>
    <div className="camera-frame">
      {transport === "WEBRTC" && !unavailable && <video ref={webrtc.videoRef} autoPlay playsInline muted aria-label="Live WebRTC annotated posture stream"/>}
      <CameraBodyOverlay landmarks={snapshot?.landmarks} region={snapshot?.ready ? null : activeRegion ?? null} state={highlightState ?? snapshot?.overall_state ?? "GREY"} mirrored={mirrored}/>
      {transport === "MJPEG" && !videoUnavailable && <img key={retryKey} src={`${mjpegUrl}?retry=${retryKey}`} alt="Annotated posture camera stream" onError={() => setMjpegFailed(true)}/>} 
      {transport === "WEBRTC" && !unavailable && webrtc.state !== "CONNECTED" && <div className="video-state"><Radio size={16}/>{webrtc.state === "CONNECTING" ? "VIDEO CONNECTING" : "VIDEO RECONNECTING"}</div>}
      {videoUnavailable && <div className="camera-placeholder"><div className="camera-symbol"><VideoOff/></div><strong>Video unavailable</strong><span>{unavailable ? "Waiting for FlexMap CV…" : "Reconnecting to the live video transport…"}</span></div>}
      {full && snapshot && <div className={`full-overlay state-${snapshot.overall_state.toLowerCase()}`}><strong>{snapshot.ready ? "Ready" : coachPrimary ?? "Adjust position"}</strong></div>}
      {research && <span className="transport-label">{transport} / {transport === "WEBRTC" ? webrtc.state : mjpegFailed ? "UNAVAILABLE" : "STREAMING"}</span>}
    </div>
  </section>;
}, (previous, next) => previous.unavailable === next.unavailable && previous.research === next.research && previous.snapshot === next.snapshot && previous.activeRegion === next.activeRegion && previous.highlightState === next.highlightState && previous.mirrored === next.mirrored && previous.coachPrimary === next.coachPrimary);