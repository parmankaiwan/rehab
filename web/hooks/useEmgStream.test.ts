import { describe, expect, it } from "vitest";
import { resolveEmgWebSocketBase } from "./useEmgStream";

describe("resolveEmgWebSocketBase", () => {
  it("connects localhost pages directly to the FastAPI port", () => {
    expect(resolveEmgWebSocketBase(new URL("http://localhost:3000/master/live/emg"))).toBe("ws://localhost:8000");
  });

  it("uses an explicitly configured backend", () => {
    expect(resolveEmgWebSocketBase(new URL("https://example.com"), "https://api.example.com/")).toBe("wss://api.example.com");
  });
});
