// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest";
import { GET } from "./route";

afterEach(() => vi.unstubAllEnvs());
it("reports the deployed commit and never echoes invalid environment contents", async () => {
  vi.stubEnv("RENDER_GIT_COMMIT", "a".repeat(40));
  expect((await GET().json()).commit).toBe("a".repeat(40));
  vi.stubEnv("RENDER_GIT_COMMIT", "not-a-commit");
  expect(await GET().json()).toEqual({ application: "flexmap-web", release: "2026-10-27-camera-emg", commit: null });
  expect(GET().headers.get("cache-control")).toBe("no-store");
});
