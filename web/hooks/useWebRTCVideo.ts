"use client";

import { RefObject, useCallback, useEffect, useRef, useState } from "react";

export type WebRTCVideoState = "CONNECTING" | "CONNECTED" | "RECONNECTING" | "UNAVAILABLE";

function waitForIceGathering(pc: RTCPeerConnection): Promise<void> {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const listener = () => {
      if (pc.iceGatheringState === "complete") {
        pc.removeEventListener("icegatheringstatechange", listener);
        resolve();
      }
    };
    pc.addEventListener("icegatheringstatechange", listener);
  });
}

export function useWebRTCVideo(enabled: boolean): {
  videoRef: RefObject<HTMLVideoElement | null>;
  state: WebRTCVideoState;
  reconnect: () => void;
} {
  const videoRef = useRef<HTMLVideoElement>(null);
  const peer = useRef<RTCPeerConnection | null>(null);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const generation = useRef(0);
  const [state, setState] = useState<WebRTCVideoState>("CONNECTING");
  const [retry, setRetry] = useState(0);

  const close = useCallback(() => {
    if (retryTimer.current) clearTimeout(retryTimer.current);
    retryTimer.current = null;
    peer.current?.close();
    peer.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  const connect = useCallback(async () => {
    if (!enabled) return;
    const attempt = ++generation.current;
    close();
    setState((current) => current === "CONNECTED" ? "RECONNECTING" : "CONNECTING");
    const pc = new RTCPeerConnection({ iceServers: [] });
    peer.current = pc;
    pc.addTransceiver("video", { direction: "recvonly" });
    pc.ontrack = (event) => {
      if (attempt !== generation.current || !videoRef.current) return;
      videoRef.current.srcObject = event.streams[0] ?? new MediaStream([event.track]);
      void videoRef.current.play();
    };
    pc.onconnectionstatechange = () => {
      if (attempt !== generation.current) return;
      if (pc.connectionState === "connected") setState("CONNECTED");
      if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
        setState("RECONNECTING");
        close();
        retryTimer.current = setTimeout(() => setRetry((value) => value + 1), 2000);
      }
    };
    try {
      await pc.setLocalDescription(await pc.createOffer());
      await waitForIceGathering(pc);
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}/api/webrtc/offer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sdp: pc.localDescription?.sdp, type: pc.localDescription?.type }),
      });
      if (!response.ok) throw new Error(`WebRTC signaling failed: ${response.status}`);
      const answer: unknown = await response.json();
      if (!answer || typeof answer !== "object" || !("sdp" in answer) || !("type" in answer)) throw new Error("Malformed WebRTC answer");
      await pc.setRemoteDescription(answer as RTCSessionDescriptionInit);
    } catch {
      if (attempt !== generation.current) return;
      setState("UNAVAILABLE");
      close();
      retryTimer.current = setTimeout(() => setRetry((value) => value + 1), 2500);
    }
  }, [close, enabled]);

  useEffect(() => {
    if (enabled) void connect(); else close();
    return () => { generation.current += 1; close(); };
  }, [close, connect, enabled, retry]);

  return { videoRef, state, reconnect: () => setRetry((value) => value + 1) };
}
