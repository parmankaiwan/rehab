// @vitest-environment node
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createServer, type Server } from "node:http";
import { gzipSync } from "node:zlib";
import { normalizeMasterResponse } from "./masterProxy";

let server: Server;
let origin = "";

beforeAll(async () => {
  server = createServer((request, response) => {
    const json = Buffer.from(JSON.stringify([{ id: "REACHING", name: "เอื้อมแขน" }]));
    if (request.url === "/gzip") {
      const compressed = gzipSync(json);
      response.writeHead(200, { "content-type": "application/json", "content-encoding": "gzip", "content-length": compressed.length, etag: "compressed-etag" });
      response.end(compressed);
      return;
    }
    response.writeHead(200, { "content-type": "application/json", "content-length": json.length });
    response.end(json);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("test server unavailable");
  origin = `http://127.0.0.1:${address.port}`;
});

afterAll(async () => { await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve())); });

describe("normalizeMasterResponse", () => {
  it("re-serializes a real gzip response without stale representation headers", async () => {
    const upstream = await fetch(`${origin}/gzip`);
    const originalLength = upstream.headers.get("content-length");
    const result = await normalizeMasterResponse(upstream, { method: "GET", path: "rehab-modules", requestId: "req-gzip" });
    expect(result.status).toBe(200);
    expect(result.headers.get("content-encoding")).toBeNull();
    expect(result.headers.get("etag")).toBeNull();
    expect(result.headers.get("content-length")).not.toBe(originalLength);
    expect(await result.json()).toEqual([{ id: "REACHING", name: "เอื้อมแขน" }]);
  });

  it("accepts plain JSON and preserves upstream error status", async () => {
    const result = await normalizeMasterResponse(new Response(JSON.stringify({ detail: "denied" }), { status: 403, headers: { "content-type": "application/json" } }), { method: "GET", path: "dataset/settings", requestId: "req-status" });
    expect(result.status).toBe(403);
    expect(await result.json()).toEqual({ detail: "denied" });
  });

  it("preserves JSON download disposition while replacing representation headers", async () => {
    const upstream = new Response(JSON.stringify({ ok: true }), { headers: { "content-type": "application/json", "content-disposition": "attachment; filename=report.json", "content-encoding": "gzip", "content-length": "7" } });
    const result = await normalizeMasterResponse(upstream, { method: "GET", path: "ml/emg-comparison/experiments/one/export.json", requestId: "req-export" });
    expect(result.headers.get("content-disposition")).toBe("attachment; filename=report.json");
    expect(result.headers.get("content-encoding")).toBeNull();
    expect(result.headers.get("content-length")).not.toBe("7");
    expect(await result.json()).toEqual({ ok: true });
  });

  it.each([
    ["truncated JSON", new Response('[{"id":"x"}', { headers: { "content-type": "application/json" } }), "UPSTREAM_INVALID_JSON"],
    ["HTML", new Response("<html>bad gateway</html>", { status: 502, headers: { "content-type": "text/html" } }), "UPSTREAM_UNEXPECTED_TYPE"],
    ["empty JSON", new Response("", { headers: { "content-type": "application/json" } }), "UPSTREAM_EMPTY_RESPONSE"],
  ])("returns a structured error for %s", async (_name, upstream, code) => {
    const result = await normalizeMasterResponse(upstream, { method: "GET", path: "rehab-modules", requestId: "req-error" });
    expect((await result.json()).error).toMatchObject({ code, request_id: "req-error" });
  });

  it("keeps bodyless responses bodyless", async () => {
    const result = await normalizeMasterResponse(new Response(null, { status: 204, headers: { "content-length": "99" } }), { method: "GET", path: "anything", requestId: "req-empty" });
    expect(result.status).toBe(204);
    expect(await result.text()).toBe("");
    expect(result.headers.get("content-length")).toBeNull();
  });

  it("streams binary range responses without JSON parsing", async () => {
    const result = await normalizeMasterResponse(new Response(new Uint8Array([2, 3]), { status: 206, headers: { "content-type": "video/webm", "content-range": "bytes 2-3/10", "content-length": "2", "accept-ranges": "bytes" } }), { method: "GET", path: "browser-collections/samples/SMP-1/artifacts/raw.webm", requestId: "req-range" });
    expect(result.status).toBe(206);
    expect(result.headers.get("content-range")).toBe("bytes 2-3/10");
    expect([...new Uint8Array(await result.arrayBuffer())]).toEqual([2, 3]);
  });

  it("preserves SVG research figure downloads", async () => {
    const svg='<svg xmlns="http://www.w3.org/2000/svg"><title>Study A</title></svg>';
    const result=await normalizeMasterResponse(new Response(svg,{headers:{"content-type":"image/svg+xml","content-disposition":"attachment; filename=study_a.svg"}}),{method:"GET",path:"ml/emg-comparison/experiments/EMGR-test/figures/study_a.svg",requestId:"figure-test"});
    expect(result.status).toBe(200);
    expect(result.headers.get("content-type")).toBe("image/svg+xml");
    expect(await result.text()).toBe(svg);
  });
});
