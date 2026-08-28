import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

export const MASTER_COOKIE = "flexmap_master_session";
export const MASTER_SESSION_SECONDS = 60 * 60 * 8;

function required(name: "MASTER_PASSWORD" | "MASTER_SESSION_SECRET"): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not configured`);
  return value;
}

function equalText(left: string, right: string): boolean {
  const a = Buffer.from(left, "utf8");
  const b = Buffer.from(right, "utf8");
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

export function verifyMasterPassword(candidate: string): boolean {
  return equalText(candidate, required("MASTER_PASSWORD"));
}

function signature(payload: string): string {
  return createHmac("sha256", required("MASTER_SESSION_SECRET")).update(payload).digest("base64url");
}

export function createMasterSession(now = Date.now()): string {
  const payload = Buffer.from(JSON.stringify({ exp: now + MASTER_SESSION_SECONDS * 1000, nonce: randomBytes(24).toString("base64url") })).toString("base64url");
  return `${payload}.${signature(payload)}`;
}

export function verifyMasterSession(token: string | undefined, now = Date.now()): boolean {
  if (!token) return false;
  const [payload, suppliedSignature, extra] = token.split(".");
  if (!payload || !suppliedSignature || extra) return false;
  if (!equalText(suppliedSignature, signature(payload))) return false;
  try {
    const parsed = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as { exp?: unknown; nonce?: unknown };
    return typeof parsed.exp === "number" && parsed.exp > now && typeof parsed.nonce === "string" && parsed.nonce.length >= 16;
  } catch {
    return false;
  }
}

export const masterCookieOptions = {
  httpOnly: true,
  sameSite: "strict" as const,
  secure: process.env.NODE_ENV === "production",
  path: "/",
  maxAge: MASTER_SESSION_SECONDS,
};
