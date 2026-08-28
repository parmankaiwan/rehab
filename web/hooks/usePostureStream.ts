"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { mockSnapshot } from "@/lib/mockPosture";
import { PostureSocket } from "@/lib/postureSocket";
import { ConnectionState, PostureSnapshot, PostureState } from "@/types/posture";
const useMock = process.env.NEXT_PUBLIC_USE_MOCK_POSTURE === "true";
export function usePostureStream() {
  const [snapshot, setSnapshot] = useState<PostureSnapshot | null>(useMock ? mockSnapshot() : null);
  const [connectionState, setConnectionState] = useState<ConnectionState>(useMock ? "CONNECTED" : "CONNECTING");
  const [now, setNow] = useState(() => Date.now()); const socket = useRef<PostureSocket | undefined>(undefined);
  useEffect(() => { const interval = setInterval(() => setNow(Date.now()), 500); if (!useMock) { socket.current = new PostureSocket(process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/posture", setSnapshot, setConnectionState); socket.current.connect(); } return () => { clearInterval(interval); socket.current?.disconnect(); }; }, []);
  const staleMs = Number(process.env.NEXT_PUBLIC_STALE_AFTER_MS ?? 2500);
  const isStale = !useMock && (!!snapshot && now - snapshot.timestamp * 1000 > staleMs);
  const setMockState = useCallback((state: PostureState) => { if (useMock) setSnapshot(mockSnapshot(state)); }, []);
  return { snapshot, connectionState, isStale, isMock: useMock, reconnect: () => socket.current?.reconnect(), setMockState };
}
