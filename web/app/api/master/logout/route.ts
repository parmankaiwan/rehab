import { NextResponse } from "next/server";
import { MASTER_COOKIE } from "@/lib/masterAuth";

export async function POST() {
  const response = NextResponse.json({ success: true }, { headers: { "Cache-Control": "no-store" } });
  response.cookies.set(MASTER_COOKIE, "", { httpOnly: true, sameSite: "strict", secure: process.env.NODE_ENV === "production", path: "/", maxAge: 0 });
  return response;
}
