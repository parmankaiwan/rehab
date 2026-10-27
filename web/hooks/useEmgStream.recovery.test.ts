import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useEmgStream } from "./useEmgStream";

class Socket {
  static instances: Socket[] = [];
  onopen?: () => void;
  onclose?: () => void;
  onerror?: () => void;
  onmessage?: (event: { data: string }) => void;
  close = vi.fn(() => this.onclose?.());
  constructor(public url: string) { Socket.instances.push(this); }
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); Socket.instances = []; });

it("recovers from unavailable tickets, reconnects sockets with fresh tickets, and cancels on unmount", async () => {
  vi.useFakeTimers();
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: false, status: 503 })
    .mockResolvedValue({ ok: true, json: async () => ({ ticket: "test-ticket" }) });
  vi.stubGlobal("fetch", fetcher);
  vi.stubGlobal("WebSocket", Socket);
  const { result, unmount } = renderHook(() => useEmgStream());
  await act(async () => {});
  expect(Socket.instances).toHaveLength(0);
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  expect(Socket.instances).toHaveLength(1);
  const first = Socket.instances[0];
  const sample = { sequence_id: 1, host_timestamp_ns: 1, channels: { channel_1: 123 }, valid: true };
  await act(async () => {
    first.onopen?.();
    first.onmessage?.({ data: JSON.stringify({ type: "emg.samples", samples: [sample] }) });
    await vi.advanceTimersByTimeAsync(50);
  });
  expect(result.current.samples).toHaveLength(1);
  await act(async () => { first.onclose?.(); await vi.advanceTimersByTimeAsync(1000); });
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(Socket.instances).toHaveLength(2);
  await act(async () => {
    Socket.instances[1].onopen?.();
    Socket.instances[1].onmessage?.({ data: "invalid JSON" });
    Socket.instances[1].onmessage?.({ data: JSON.stringify({ type: "emg.samples", samples: [sample] }) });
    await vi.advanceTimersByTimeAsync(50);
  });
  expect(result.current.samples).toHaveLength(1); // no duplicate replay
  unmount();
  await act(async () => { await vi.advanceTimersByTimeAsync(20000); });
  expect(fetcher).toHaveBeenCalledTimes(3);
});
