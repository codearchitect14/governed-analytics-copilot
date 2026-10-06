import { useAuth, type SessionUser } from "./auth-store";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

interface TokenResponse {
  access_token: string;
  expires_at: string;
  user: SessionUser;
}

let refreshing: Promise<boolean> | null = null;
let refreshTimer: ReturnType<typeof setTimeout> | undefined;
const REFRESH_LEAD_MS = 60_000;

/** Exchanges the httpOnly refresh cookie for a new access token. Concurrent callers share one request. */
export function refreshSession(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch("/api/v1/auth/refresh", { method: "POST", credentials: "same-origin" })
      .then(async (response) => {
        if (!response.ok) {
          useAuth.getState().clear();
          return false;
        }
        const body = (await response.json()) as TokenResponse;
        useAuth.getState().setSession(body.user, body.access_token, body.expires_at);
        scheduleRefresh(body.expires_at);
        return true;
      })
      .catch(() => {
        useAuth.getState().clear();
        return false;
      })
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

/** Refreshes shortly before the access token expires, so that the session continues silently. */
export function scheduleRefresh(expiresAt: string): void {
  if (refreshTimer) clearTimeout(refreshTimer);
  const delay = Math.max(Date.parse(expiresAt) - Date.now() - REFRESH_LEAD_MS, 5_000);
  refreshTimer = setTimeout(() => {
    void refreshSession();
  }, delay);
}

export function stopRefresh(): void {
  if (refreshTimer) clearTimeout(refreshTimer);
}

export async function login(email: string, password: string): Promise<void> {
  const response = await fetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new ApiError(response.status, body.detail ?? "Sign in failed");
  }
  const body = (await response.json()) as TokenResponse;
  useAuth.getState().setSession(body.user, body.access_token, body.expires_at);
  scheduleRefresh(body.expires_at);
}

export async function logout(): Promise<void> {
  stopRefresh();
  await fetch("/api/v1/auth/logout", { method: "POST", credentials: "same-origin" }).catch(() => undefined);
  useAuth.getState().clear();
}

/** Fetch with the in-memory bearer token. Retries once after a silent refresh on 401. */
export async function apiFetch(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const token = useAuth.getState().accessToken;
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, headers, credentials: "same-origin" });
  if (response.status === 401 && retry && (await refreshSession())) {
    return apiFetch(path, init, false);
  }
  return response;
}

/** JSON helper that throws ApiError with the server's safe message. */
export async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiFetch(path, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
    const message = typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`;
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
