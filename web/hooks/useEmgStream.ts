"use client";

import { useEffect, useRef, useState } from "react";
import type { EmgSample, EmgStatus } from "@/types/emg";

export function resolveEmgWebSocketBase(pageUrl: URL, configured?: string) {
  if (configured) return configured.replace(/^http/, "ws").replace(/\/$/, "");
  if (["localhost", "127.0.0.1", "[::1]"].includes(pageUrl.hostname)) {
    return `ws://${pageUrl.hostname}:8000`;
  }
  return pageUrl.origin.replace(/^http/, "ws");
}

export function useEmgStream(enabled = true) {
  const [samples, setSamples] = useState<EmgSample[]>([]);
  const [status, setStatus] = useState<EmgStatus | null>(null);
  const latest = useRef<EmgSample[]>([]);

  useEffect(() => {
    if (!enabled) return;
    let ws: WebSocket | undefined;
    let dead = false;

    fetch("/api/master/data/emg/ws-ticket", { method: "POST" })
      .then(async (response) => {
        if (!response.ok) throw new Error(`EMG ticket failed: ${response.status}`);
        return response.json() as Promise<{ ticket: string }>;
      })
      .then(({ ticket }) => {
        if (dead) return;
        const configured = process.env.NEXT_PUBLIC_EMG_WS_URL || process.env.NEXT_PUBLIC_BACKEND_URL;
        const base = resolveEmgWebSocketBase(new URL(window.location.href), configured);
        ws = new WebSocket(`${base}/ws/emg?ticket=${encodeURIComponent(ticket)}`);
        ws.onmessage = (event) => {
          const message = JSON.parse(event.data);
          if (message.type === "emg.samples") {
            latest.current.push(...message.samples);
            if (latest.current.length > 35000) latest.current.splice(0, latest.current.length - 35000);
          } else if (message.type === "emg.status") {
            setStatus(message);
          }
        };
      })
      .catch((error) => console.error("EMG WebSocket setup failed", error));

    const timer = window.setInterval(() => setSamples(latest.current.slice()), 50);
    return () => {
      dead = true;
      clearInterval(timer);
      ws?.close();
    };
  }, [enabled]);

  return {
    samples,
    status,
    clear: () => {
      latest.current = [];
      setSamples([]);
    },
  };
}
