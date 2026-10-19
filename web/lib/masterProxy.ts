const DEFAULT_JSON_LIMIT = 5 * 1024 * 1024;

export type ProxyErrorCode =
  | "UPSTREAM_INVALID_JSON"
  | "UPSTREAM_EMPTY_RESPONSE"
  | "UPSTREAM_RESPONSE_TOO_LARGE"
  | "UPSTREAM_UNEXPECTED_TYPE";

function errorBody(code: ProxyErrorCode, requestId: string) {
  const messages: Record<ProxyErrorCode, string> = {
    UPSTREAM_INVALID_JSON: "The data service returned an invalid response.",
    UPSTREAM_EMPTY_RESPONSE: "The data service returned an empty response.",
    UPSTREAM_RESPONSE_TOO_LARGE: "The data service response exceeded the safe JSON limit.",
    UPSTREAM_UNEXPECTED_TYPE: "The data service returned an unexpected response type.",
  };
  return { error: { code, message: messages[code], request_id: requestId } };
}

function jsonResponse(body: unknown, status: number, requestId: string, upstream?: Response) {
  const headers = new Headers({
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "x-request-id": requestId,
  });
  const disposition = upstream?.headers.get("content-disposition");
  if (disposition) headers.set("content-disposition", disposition);
  return new Response(JSON.stringify(body), { status, headers });
}

function isJsonType(value: string) {
  const type = value.split(";", 1)[0].trim().toLowerCase();
  return type === "application/json" || type.endsWith("+json");
}

function isBinaryPath(path: string) {
  return /\/(?:files|artifacts|media|download)(?:\/|$)/i.test(path)
    || /\/(?:manifest|training-manifest|export)(?:\/|$)/i.test(path)
    || /\.(?:csv|zip|mp4|webm|jpe?g|png|bin)$/i.test(path);
}

function validateExpectedShape(path: string, value: unknown) {
  if (/^rehab-modules\/?$/i.test(path) && !Array.isArray(value)) return false;
  return true;
}

function safeStreamingHeaders(upstream: Response) {
  const headers = new Headers({ "cache-control": "no-store" });
  const encoded = Boolean(upstream.headers.get("content-encoding"));
  for (const name of ["content-type", "content-disposition", "accept-ranges"]) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  // fetch transparently decodes compressed responses. Metadata describing the
  // compressed representation is therefore unsafe on the outgoing response.
  if (!encoded) {
    for (const name of ["content-length", "content-range", "etag", "last-modified"]) {
      const value = upstream.headers.get(name);
      if (value) headers.set(name, value);
    }
  }
  return headers;
}

export async function normalizeMasterResponse(
  upstream: Response,
  options: { method: string; path: string; requestId: string; jsonLimitBytes?: number },
) {
  const { method, path, requestId } = options;
  const bodyless = method === "HEAD" || [204, 205, 304].includes(upstream.status);
  if (bodyless) {
    const headers = safeStreamingHeaders(upstream);
    headers.delete("content-length");
    headers.delete("content-range");
    headers.set("x-request-id", requestId);
    return new Response(null, { status: upstream.status, headers });
  }

  const contentType = upstream.headers.get("content-type") || "";
  const jsonExpected = isJsonType(contentType) || !isBinaryPath(path);
  if (!jsonExpected) {
    const headers = safeStreamingHeaders(upstream);
    headers.set("x-request-id", requestId);
    return new Response(upstream.body, { status: upstream.status, headers });
  }

  if (!isJsonType(contentType)) {
    return jsonResponse(errorBody("UPSTREAM_UNEXPECTED_TYPE", requestId), upstream.status || 502, requestId);
  }

  const declared = Number(upstream.headers.get("content-length") || 0);
  const limit = options.jsonLimitBytes ?? DEFAULT_JSON_LIMIT;
  if (declared > limit && !upstream.headers.get("content-encoding")) {
    return jsonResponse(errorBody("UPSTREAM_RESPONSE_TOO_LARGE", requestId), 502, requestId);
  }
  const bytes = new Uint8Array(await upstream.arrayBuffer());
  if (bytes.byteLength > limit) {
    return jsonResponse(errorBody("UPSTREAM_RESPONSE_TOO_LARGE", requestId), 502, requestId);
  }
  if (!bytes.byteLength) {
    return jsonResponse(errorBody("UPSTREAM_EMPTY_RESPONSE", requestId), upstream.ok ? 502 : upstream.status, requestId);
  }
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    const value: unknown = JSON.parse(text);
    if (!validateExpectedShape(path, value)) {
      return jsonResponse(errorBody("UPSTREAM_INVALID_JSON", requestId), upstream.ok ? 502 : upstream.status, requestId);
    }
    return jsonResponse(value, upstream.status, requestId, upstream);
  } catch {
    return jsonResponse(errorBody("UPSTREAM_INVALID_JSON", requestId), upstream.ok ? 502 : upstream.status, requestId);
  }
}
