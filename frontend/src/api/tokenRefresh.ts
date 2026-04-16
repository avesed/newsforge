import { safeGetItem, safeRemoveItem, safeSetItem } from "@/lib/storage";

const ACCESS_KEY = "access_token";
const REFRESH_KEY = "refresh_token";
const REFRESH_ENDPOINT = "/api/v1/auth/refresh";

let refreshPromise: Promise<string> | null = null;

export function getAccessToken(): string | null {
  return safeGetItem(ACCESS_KEY);
}

export function setTokens(accessToken: string, refreshToken: string): void {
  safeSetItem(ACCESS_KEY, accessToken);
  safeSetItem(REFRESH_KEY, refreshToken);
}

export function clearTokens(): void {
  safeRemoveItem(ACCESS_KEY);
  safeRemoveItem(REFRESH_KEY);
}

export function hardLogout(): void {
  clearTokens();
  const path = window.location.pathname;
  if (path !== "/login" && path !== "/register") {
    window.location.href = "/login";
  }
}

const PENDING_REFRESH_TIMEOUT_MS = 3000;

/**
 * Wait for any currently in-flight refresh to settle. Resolves immediately
 * if none is running. Callers that need to read the *latest* refresh token
 * from storage (e.g. logout) should await this first so they don't grab a
 * stale pre-rotation value.
 *
 * Bounded by a short timeout: if refresh is hung (slow backend, dropped
 * network), logout must still complete — we'd rather send a pre-rotation
 * refresh token that the server rejects than leave the UI stuck.
 *
 * MUST NOT be called from inside the refresh body itself (would self-await).
 */
export async function awaitPendingRefresh(): Promise<void> {
  if (!refreshPromise) return;
  const timeout = new Promise<void>((resolve) =>
    setTimeout(resolve, PENDING_REFRESH_TIMEOUT_MS)
  );
  try {
    await Promise.race([refreshPromise, timeout]);
  } catch {
    // swallow — caller only cares that we're no longer mid-rotation
  }
}

/**
 * Silently refresh the access token. Concurrent callers share one in-flight
 * request so we never fire N refreshes for N parallel 401s.
 *
 * Uses plain fetch (not the axios client) so a 401 from the refresh endpoint
 * itself doesn't recurse into the interceptor.
 */
export function refreshAccessToken(): Promise<string> {
  refreshPromise ??= (async () => {
    const rt = safeGetItem(REFRESH_KEY);
    if (!rt) throw new Error("no refresh token");
    const resp = await fetch(REFRESH_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refreshToken: rt }),
    });
    if (!resp.ok) throw new Error(`refresh failed: ${resp.status}`);
    const data = (await resp.json()) as {
      accessToken: string;
      refreshToken: string;
    };
    setTokens(data.accessToken, data.refreshToken);
    return data.accessToken;
  })().finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}
