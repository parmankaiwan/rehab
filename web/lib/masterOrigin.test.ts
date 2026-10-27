// @vitest-environment node
import { describe, expect, it } from "vitest";
import { isMasterMutationOriginAllowed as allowed } from "./masterOrigin";

describe("Master mutation origin behind Render TLS proxy", () => {
  it("accepts configured public HTTPS origin despite an internal HTTP request URL", () => {
    expect(allowed("https://flexmap.example", "http://localhost:10000", "https://flexmap.example")).toBe(true);
  });
  it("preserves direct local requests and authenticated non-browser callers", () => {
    expect(allowed("http://localhost:3000", "http://localhost:3000")).toBe(true);
    expect(allowed(null, "http://localhost:3000")).toBe(true);
  });
  it("rejects foreign origins, suffix attacks, null origins and malformed configuration", () => {
    for (const origin of ["https://evil.example", "https://flexmap.example.evil", "null", "https://flexmap.example/path"]) {
      expect(allowed(origin, "http://localhost:10000", "https://flexmap.example")).toBe(false);
    }
    expect(allowed("https://flexmap.example", "http://localhost:10000", "not a URL")).toBe(false);
  });
});
