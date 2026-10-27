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
    let retry: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;

    function reconnect() {
      if (dead || retry !== undefined) return;
      retry = setTimeout(() => {
        retry = undefined;
        connect();
      }, Math.min(1000 * 2 ** Math.min(attempt++, 4), 15000));
    }

    function connect() {
      if (dead) return;
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
        ws.onopen = () => {
          attempt = 0;
          // The server sends its current ring buffer on each new connection.
          // Do not append that replay to samples from the previous connection.
          latest.current = [];
        };
        ws.onclose = reconnect;
        ws.onerror = () => ws?.close();
        ws.onmessage = (event) => {
          if (dead) return;
          let message;
          try { message = JSON.parse(event.data); } catch { return; }
          if (message.type === "emg.samples") {
            latest.current.push(...message.samples);
            if (latest.current.length > 35000) latest.current.splice(0, latest.current.length - 35000);
          } else if (message.type === "emg.status") {
            setStatus(message);
          }
        };
      })
      .catch(() => reconnect());
    }
    connect();

    const timer = window.setInterval(() => setSamples(latest.current.slice()), 50);
    return () => {
      dead = true;
      if (retry !== undefined) clearTimeout(retry);
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
