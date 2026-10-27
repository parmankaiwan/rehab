// Trust deployment configuration, never arbitrary forwarded request headers.
export function isMasterMutationOriginAllowed(origin: string | null, requestOrigin: string, publicUrl?: string) {
  if (!origin) return true; // Non-browser callers still require Master authentication.
  try {
    const supplied = new URL(origin);
    if (supplied.origin !== origin || !["http:", "https:"].includes(supplied.protocol)) return false;
    if (origin === new URL(requestOrigin).origin) return true;
    return Boolean(publicUrl && origin === new URL(publicUrl).origin);
  } catch {
    return false;
  }
}
