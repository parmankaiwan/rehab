import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { MASTER_COOKIE, verifyMasterSession } from "@/lib/masterAuth";

export async function GET() {
  const cookieStore = await cookies();
  return NextResponse.json({ authenticated: verifyMasterSession(cookieStore.get(MASTER_COOKIE)?.value) }, { headers: { "Cache-Control": "no-store" } });
}
