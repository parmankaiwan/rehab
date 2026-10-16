export type MasterApiErrorCode =
  | "NOT_AUTHENTICATED" | "API_UNAVAILABLE" | "API_WAKING"
  | "UPSTREAM_INVALID_JSON" | "UPSTREAM_EMPTY_RESPONSE" | "UPSTREAM_UNEXPECTED_TYPE"
  | "DATABASE_NOT_CONFIGURED" | "MIGRATION_REQUIRED" | "STORAGE_UNAVAILABLE"
  | "EMPTY_DATASET" | "NETWORK_TIMEOUT" | "HTTP_ERROR";

export class MasterApiError extends Error {
  constructor(public code: MasterApiErrorCode, message: string, public status = 0, public requestId?: string) {
    super(message);
    this.name = "MasterApiError";
  }
}

const retryable = new Set(["API_UNAVAILABLE", "API_WAKING", "NETWORK_TIMEOUT"]);

function mappedCode(status: number, supplied?: string): MasterApiErrorCode {
  if (supplied) return supplied as MasterApiErrorCode;
  if (status === 401 || status === 403) return "NOT_AUTHENTICATED";
  if (status === 502) return "API_UNAVAILABLE";
  if (status === 503) return "API_WAKING";
  if (status === 504) return "NETWORK_TIMEOUT";
  return "HTTP_ERROR";
}

export async function masterApiGet<T>(url: string, options: { retries?: number; timeoutMs?: number; validate?: (value: unknown) => value is T } = {}): Promise<T> {
  const retries = Math.max(0, Math.min(options.retries ?? 2, 3));
  let last: MasterApiError | undefined;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? 12_000);
    try {
      const response = await fetch(url, { cache: "no-store", signal: controller.signal });
      let payload: unknown;
      try {
        if (typeof response.text === "function") {
          const text = await response.text();
          payload = text ? JSON.parse(text) : undefined;
        } else {
          // Keeps the helper usable with minimal Response doubles in unit tests.
          payload = await response.json();
        }
      }
      catch { throw new MasterApiError("UPSTREAM_INVALID_JSON", "The server returned invalid JSON.", response.status); }
      const structured = payload && typeof payload === "object" && "error" in payload ? (payload as { error?: { code?: string; message?: string; request_id?: string } }).error : undefined;
      if (!response.ok) throw new MasterApiError(mappedCode(response.status, structured?.code), structured?.message || `Request failed (${response.status}).`, response.status, structured?.request_id);
      if (payload === undefined) throw new MasterApiError("UPSTREAM_EMPTY_RESPONSE", "The server returned an empty response.", response.status);
      if (options.validate && !options.validate(payload)) throw new MasterApiError("UPSTREAM_INVALID_JSON", "The server returned an unexpected data shape.", response.status);
      return payload as T;
    } catch (cause) {
      last = cause instanceof MasterApiError ? cause : new MasterApiError(cause instanceof Error && cause.name === "AbortError" ? "NETWORK_TIMEOUT" : "API_UNAVAILABLE", cause instanceof Error && cause.name === "AbortError" ? "The request timed out." : "The data service is unavailable.");
      if (attempt >= retries || !retryable.has(last.code)) throw last;
      await new Promise((resolve) => setTimeout(resolve, [300, 800, 1600][attempt]));
    } finally { clearTimeout(timer); }
  }
  throw last ?? new MasterApiError("API_UNAVAILABLE", "The data service is unavailable.");
}

export function apiErrorMessage(cause: unknown) {
  if (!(cause instanceof MasterApiError)) return "The data service is unavailable.";
  const labels: Partial<Record<MasterApiErrorCode, string>> = {
    NOT_AUTHENTICATED: "Your Master session has expired. Sign in again.",
    API_UNAVAILABLE: "The data service is unavailable.", API_WAKING: "The data service is waking up. Please retry shortly.",
    NETWORK_TIMEOUT: "The data service took too long to respond.", DATABASE_NOT_CONFIGURED: "The database is not configured.",
    MIGRATION_REQUIRED: "The required database migration has not been applied.", STORAGE_UNAVAILABLE: "Private artifact storage is unavailable.",
    UPSTREAM_INVALID_JSON: "The data service returned an invalid response.", UPSTREAM_EMPTY_RESPONSE: "The data service returned an empty response.",
    UPSTREAM_UNEXPECTED_TYPE: "The data service returned an unexpected response type.", EMPTY_DATASET: "No dataset records exist yet.",
  };
  return labels[cause.code] || cause.message;
}
