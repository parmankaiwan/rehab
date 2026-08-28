import { beforeEach, describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { createMasterSession, MASTER_COOKIE, verifyMasterPassword, verifyMasterSession } from "./masterAuth";
import { resetMasterRateLimitForTests } from "./masterRateLimit";
import { POST as login } from "@/app/api/master/login/route";
import { POST as logout } from "@/app/api/master/logout/route";

const TEST_PASSWORD = "unit-test-password";
const TEST_SECRET = "unit-test-session-secret-that-is-long-and-private";

function request(password: string, ip = "127.0.0.1") {
  return new NextRequest("http://localhost/api/master/login", { method: "POST", headers: { "content-type": "application/json", "x-forwarded-for": ip }, body: JSON.stringify({ password }) });
}

describe("Master server authentication", () => {
  beforeEach(() => {
    process.env.MASTER_PASSWORD = TEST_PASSWORD;
    process.env.MASTER_SESSION_SECRET = TEST_SECRET;
    resetMasterRateLimitForTests();
  });

  it("rejects missing, expired, and modified sessions", () => {
    expect(verifyMasterSession(undefined)).toBe(false);
    const token = createMasterSession(1_000);
    expect(verifyMasterSession(token, 1_001)).toBe(true);
    expect(verifyMasterSession(token, 1_000 + 8 * 60 * 60 * 1000 + 1)).toBe(false);
    expect(verifyMasterSession(`${token}x`, 1_001)).toBe(false);
  });

  it("uses the server-side password", () => {
    expect(verifyMasterPassword(TEST_PASSWORD)).toBe(true);
    expect(verifyMasterPassword("incorrect")).toBe(false);
  });

  it("authenticates and creates a signed HttpOnly session", async () => {
    const response = await login(request(TEST_PASSWORD));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ success: true });
    const cookie = response.headers.get("set-cookie") || "";
    expect(cookie).toContain(`${MASTER_COOKIE}=`);
    expect(cookie).toMatch(/HttpOnly/i);
    expect(cookie).toMatch(/SameSite=strict/i);
    expect(cookie).not.toContain(TEST_PASSWORD);
  });

  it("rejects an incorrect password without a session", async () => {
    const response = await login(request("incorrect"));
    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ success: false, error: "Invalid password" });
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("rate limits repeated failures", async () => {
    for (let attempt = 0; attempt < 5; attempt += 1) expect((await login(request("incorrect", "rate-test"))).status).toBe(401);
    expect((await login(request("incorrect", "rate-test"))).status).toBe(429);
  });

  it("logout expires the session cookie", async () => {
    const response = await logout();
    expect(response.status).toBe(200);
    const cookie = response.headers.get("set-cookie") || "";
    expect(cookie).toContain(`${MASTER_COOKIE}=`);
    expect(cookie).toMatch(/Max-Age=0/i);
  });
});
