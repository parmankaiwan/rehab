import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { MASTER_COOKIE, verifyMasterSession } from "@/lib/masterAuth";

export const dynamic = "force-dynamic";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const jar = await cookies();
  if (!verifyMasterSession(jar.get(MASTER_COOKIE)?.value)) return NextResponse.json({ error: "Master authorization required" }, { status: 401 });
  const token = process.env.MASTER_INTERNAL_TOKEN;
  if (!token) return NextResponse.json({ error: "Master data service is not configured" }, { status: 503 });
  const backendUrl = process.env.FLEXMAP_BACKEND_URL
    ?? (process.env.FLEXMAP_BACKEND_HOST ? `http://${process.env.FLEXMAP_BACKEND_HOST}` : undefined)
    ?? (process.env.NODE_ENV === "development" ? "http://127.0.0.1:8000" : undefined);
  if (!backendUrl) return NextResponse.json({ error: "Master data service is not configured" }, { status: 503 });
  const { path } = await context.params;
  const upstream = new URL(`/api/master/${path.join("/")}`, backendUrl);
  upstream.search = request.nextUrl.search;
  const headers = new Headers();
  headers.set("x-flexmap-master-token", token);
  const contentType = request.headers.get("content-type"); if (contentType) headers.set("content-type", contentType);
  const range = request.headers.get("range"); if (range) headers.set("range", range);
  const controller = request.headers.get("x-flexmap-controller-id"); if (controller) headers.set("x-flexmap-controller-id", controller);
  try {
    const response = await fetch(upstream, { method: request.method, headers, body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer(), cache: "no-store" });
    const forwarded = new Headers();
    for (const name of ["content-type", "content-length", "content-range", "accept-ranges", "content-disposition", "etag", "last-modified"]) { const value = response.headers.get(name); if (value) forwarded.set(name, value); }
    forwarded.set("cache-control", "no-store");
    return new NextResponse(response.body, { status: response.status, headers: forwarded });
  } catch { return NextResponse.json({ error: "Master data service is unavailable" }, { status: 502 }); }
}

export const GET = proxy; export const HEAD = proxy; export const POST = proxy; export const PUT = proxy; export const PATCH = proxy; export const DELETE = proxy;
