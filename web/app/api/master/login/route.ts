import { NextRequest, NextResponse } from "next/server";
import { createMasterSession, masterCookieOptions, MASTER_COOKIE, verifyMasterPassword } from "@/lib/masterAuth";
import { clearLoginFailures, loginKey, rateLimitStatus, recordLoginFailure } from "@/lib/masterRateLimit";

export async function POST(request: NextRequest) {
  const key = loginKey(request.headers);
  const limit = rateLimitStatus(key);
  if (!limit.allowed) return NextResponse.json({ success: false, error: "Too many attempts. Try again later." }, { status: 429, headers: { "Retry-After": String(limit.retryAfter), "Cache-Control": "no-store" } });
  let password: unknown;
  try {
    const body: unknown = await request.json();
    password = typeof body === "object" && body !== null && "password" in body
      ? (body as { password?: unknown }).password
      : undefined;
  } catch { return NextResponse.json({ success: false, error: "Invalid request" }, { status: 400 }); }
  if (typeof password !== "string" || !verifyMasterPassword(password)) {
    recordLoginFailure(key);
    return NextResponse.json({ success: false, error: "Invalid password" }, { status: 401, headers: { "Cache-Control": "no-store" } });
  }
  clearLoginFailures(key);
  const response = NextResponse.json({ success: true }, { headers: { "Cache-Control": "no-store" } });
  response.cookies.set(MASTER_COOKIE, createMasterSession(), masterCookieOptions);
  return response;
}
