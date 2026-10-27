import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export function GET() {
  const commit = process.env.RENDER_GIT_COMMIT || "";
  return NextResponse.json({ application: "flexmap-web", release: "2026-10-27-camera-emg", commit: /^[0-9a-f]{40}$/.test(commit) ? commit : null }, { headers: { "cache-control": "no-store" } });
}
