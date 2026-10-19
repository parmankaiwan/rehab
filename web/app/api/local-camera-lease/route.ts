import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  if (process.env.FLEXMAP_LOCAL_LIFECYCLE_ENABLED !== "true") {
    return NextResponse.json({ accepted: false, mode: "HOSTED" }, { status: 409 });
  }
  const origin = request.headers.get("origin");
  if (origin && origin !== request.nextUrl.origin) {
    return NextResponse.json({ accepted: false, error: "Cross-origin camera lease rejected" }, { status: 403 });
  }
  const token = process.env.MASTER_INTERNAL_TOKEN;
  if (!token) return NextResponse.json({ accepted: false, error: "Local bridge is not configured" }, { status: 503 });
  const backend = process.env.FLEXMAP_BACKEND_URL || "http://127.0.0.1:8000";
  if (!backend.startsWith("http://127.0.0.1:") && !backend.startsWith("http://localhost:")) {
    return NextResponse.json({ accepted: false, error: "Camera lease requires the local backend" }, { status: 409 });
  }
  const body = await request.text();
  try {
    const response = await fetch(new URL("/api/master/lifecycle/camera-lease", backend), {
      method: "POST",
      headers: { "content-type": "application/json", "x-flexmap-master-token": token },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    return new NextResponse(await response.text(), {
      status: response.status,
      headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
    });
  } catch {
    return NextResponse.json({ accepted: false, error: "Local supervisor is unavailable" }, { status: 503 });
  }
}
