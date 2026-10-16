import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { MASTER_COOKIE, verifyMasterSession } from "@/lib/masterAuth";
import { normalizeMasterResponse } from "@/lib/masterProxy";

export const dynamic = "force-dynamic";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const requestId = crypto.randomUUID();
  const jar = await cookies();
  if (!verifyMasterSession(jar.get(MASTER_COOKIE)?.value)) return NextResponse.json({ error: { code: "NOT_AUTHENTICATED", message: "Master authorization required.", request_id: requestId } }, { status: 401 });
  if (!["GET", "HEAD"].includes(request.method)) {
    const origin = request.headers.get("origin");
    if (origin && origin !== request.nextUrl.origin) return NextResponse.json({ error: { code: "CROSS_ORIGIN_REJECTED", message: "Cross-origin Master mutation rejected.", request_id: requestId } }, { status: 403 });
  }
  const token = process.env.MASTER_INTERNAL_TOKEN;
  if (!token) return NextResponse.json({ error: { code: "DATABASE_NOT_CONFIGURED", message: "Master data service is not configured.", request_id: requestId } }, { status: 503 });
  // Render free services cannot receive private-network traffic. Keep the
  // production public endpoint as a code fallback so an old Blueprint-only
  // FLEXMAP_BACKEND_HOST value can never break the Master proxy with 502s.
  const backendUrl = process.env.FLEXMAP_BACKEND_URL
    ?? (process.env.NODE_ENV === "production"
      ? "https://flexmap-rehab-api-parmankaiwan.onrender.com"
      : "http://127.0.0.1:8000");
  if (!backendUrl) return NextResponse.json({ error: { code: "DATABASE_NOT_CONFIGURED", message: "Master data service is not configured.", request_id: requestId } }, { status: 503 });
  const { path } = await context.params;
  const upstream = new URL(`/api/master/${path.join("/")}`, backendUrl);
  upstream.search = request.nextUrl.search;
  const headers = new Headers();
  headers.set("x-flexmap-master-token", token);
  const contentType = request.headers.get("content-type"); if (contentType) headers.set("content-type", contentType);
  const range = request.headers.get("range"); if (range) headers.set("range", range);
  const controller = request.headers.get("x-flexmap-controller-id"); if (controller) headers.set("x-flexmap-controller-id", controller);
  headers.set("x-request-id", requestId);
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), 20_000);
  try {
    const init: RequestInit & { duplex?: "half" } = { method: request.method, headers, body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body, cache: "no-store", signal: timeout.signal };
    if (init.body) init.duplex = "half";
    const response = await fetch(upstream, init);
    return await normalizeMasterResponse(response, { method: request.method, path: path.join("/"), requestId });
  } catch (cause) {
    const timedOut = cause instanceof Error && cause.name === "AbortError";
    return NextResponse.json({ error: { code: timedOut ? "NETWORK_TIMEOUT" : "API_UNAVAILABLE", message: timedOut ? "The data service timed out." : "The data service is unavailable.", request_id: requestId } }, { status: timedOut ? 504 : 502 });
  } finally { clearTimeout(timer); }
}

export const GET = proxy; export const HEAD = proxy; export const POST = proxy; export const PUT = proxy; export const PATCH = proxy; export const DELETE = proxy;
