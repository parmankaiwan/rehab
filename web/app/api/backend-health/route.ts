import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  const backendUrl = process.env.FLEXMAP_BACKEND_URL
    ?? (process.env.NODE_ENV === "production"
      ? "https://flexmap-rehab-api-parmankaiwan.onrender.com"
      : "http://127.0.0.1:8000");
  try {
    const response = await fetch(new URL("/health", backendUrl), { cache: "no-store" });
    return NextResponse.json({ website: "ok", api: response.ok ? "ok" : "error", apiStatus: response.status }, { status: response.ok ? 200 : 502 });
  } catch {
    return NextResponse.json({ website: "ok", api: "unreachable" }, { status: 502 });
  }
}
