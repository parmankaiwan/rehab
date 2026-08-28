type Attempt = { failures: number; resetAt: number };

const WINDOW_MS = 15 * 60 * 1000;
const MAX_FAILURES = 5;
const globalLimiter = globalThis as typeof globalThis & { __flexmapMasterAttempts?: Map<string, Attempt> };
const attempts = globalLimiter.__flexmapMasterAttempts ??= new Map<string, Attempt>();

export function loginKey(headers: Headers): string {
  return headers.get("x-forwarded-for")?.split(",")[0]?.trim() || headers.get("x-real-ip") || "local";
}

export function rateLimitStatus(key: string, now = Date.now()): { allowed: boolean; retryAfter: number } {
  const attempt = attempts.get(key);
  if (!attempt || attempt.resetAt <= now) {
    if (attempt) attempts.delete(key);
    return { allowed: true, retryAfter: 0 };
  }
  return { allowed: attempt.failures < MAX_FAILURES, retryAfter: Math.ceil((attempt.resetAt - now) / 1000) };
}

export function recordLoginFailure(key: string, now = Date.now()): void {
  const current = attempts.get(key);
  attempts.set(key, !current || current.resetAt <= now ? { failures: 1, resetAt: now + WINDOW_MS } : { ...current, failures: current.failures + 1 });
}

export function clearLoginFailures(key: string): void { attempts.delete(key); }

export function resetMasterRateLimitForTests(): void { attempts.clear(); }
