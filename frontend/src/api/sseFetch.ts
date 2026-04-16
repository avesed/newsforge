import { getAccessToken, hardLogout, refreshAccessToken } from "./tokenRefresh";

/**
 * Fetch wrapper for Server-Sent Event streams. Behaves like native fetch but:
 * - auto-attaches Bearer token from localStorage
 * - on 401, triggers a silent refresh once, then retries the request
 *
 * Caller is responsible for reading the stream body and for reconnect logic.
 */
export async function sseFetch(
  url: string,
  init: RequestInit = {}
): Promise<Response> {
  const attempt = async (token: string | null): Promise<Response> => {
    const headers = new Headers(init.headers);
    if (!headers.has("Accept")) headers.set("Accept", "text/event-stream");
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return fetch(url, { ...init, headers });
  };

  const initialToken = getAccessToken();
  const response = await attempt(initialToken);
  if (response.status !== 401) return response;

  // Drain the 401 body so the connection can be reused.
  try {
    await response.body?.cancel();
  } catch {
    // ignore
  }

  // Anonymous callers (e.g. ArticlePage hitting an optional-auth stream)
  // should never be force-navigated to /login on a spurious 401 — they
  // weren't logged in to begin with. Only attempt refresh when we actually
  // had a token that might be stale.
  if (!initialToken) return response;

  try {
    const newToken = await refreshAccessToken();
    return attempt(newToken);
  } catch {
    // Refresh exhausted — the session is dead. Tear down auth state so
    // callers (SSE hooks with exponential reconnect) don't hammer /refresh
    // with a guaranteed-bad token. hardLogout navigates to /login.
    hardLogout();
    return response;
  }
}
