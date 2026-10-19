import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json(
    { application: "flexmap-web", status: "ready" },
    { headers: { "cache-control": "no-store" } },
  );
}
