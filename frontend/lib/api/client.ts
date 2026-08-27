import { clearTokens, getTokens, setTokens } from "./token-store";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

// FastAPI puts the reason under `detail`: a plain string for our HTTPExceptions, but an
// array of {loc, msg, ...} objects for 422 validation errors. String()-ing the latter gives
// "[object Object]", so pull out the msg(s) instead.
function formatDetail(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail.map((e) => (e && typeof e === "object" && "msg" in e ? String((e as { msg: unknown }).msg) : String(e)));
    if (msgs.length) return msgs.join("; ");
  }
  return `Request failed (${status})`;
}

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown) {
    super(formatDetail(body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : undefined, status));
    this.status = status;
    this.body = body;
  }
}

/**
 * The API host could not be reached at all — wrong port, backend down, DNS,
 * offline. Distinct from ApiError, which means the server answered.
 *
 * Worth its own type because the two are indistinguishable to a user otherwise:
 * a dead backend and a wrong password both used to surface as "Login failed",
 * which sends people hunting for a credential problem that isn't there.
 */
export class NetworkError extends Error {
  readonly url: string;

  constructor(url: string, cause?: unknown) {
    super(`Cannot reach the API at ${url}. Check that the backend is running and that NEXT_PUBLIC_API_BASE_URL points at it.`);
    this.name = "NetworkError";
    this.url = url;
    this.cause = cause;
  }
}

/** fetch() rejects (rather than resolving non-2xx) only when the request never completed. */
async function fetchOrThrow(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (cause) {
    throw new NetworkError(API_BASE_URL, cause);
  }
}

let refreshInFlight: Promise<boolean> | null = null;

export async function tryRefresh(): Promise<boolean> {
  const { refreshToken } = getTokens();
  if (!refreshToken) return false;

  if (!refreshInFlight) {
    refreshInFlight = fetch(`${API_BASE_URL}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
      .then(async (res) => {
        if (!res.ok) return false;
        const data = await res.json();
        setTokens({ accessToken: data.access_token, refreshToken: data.refresh_token });
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

export async function apiFetch<T>(path: string, options: RequestInit = {}, _retried = false): Promise<T> {
  const { accessToken } = getTokens();
  const headers = new Headers(options.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (options.body && !headers.has("Content-Type") && typeof options.body === "string") {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetchOrThrow(`${API_BASE_URL}${path}`, { ...options, headers });

  if (res.status === 401 && !_retried && accessToken) {
    const refreshed = await tryRefresh();
    if (refreshed) return apiFetch<T>(path, options, true);
    clearTokens();
  }

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export async function apiFetchBlob(path: string, options: RequestInit = {}, _retried = false): Promise<Blob> {
  const { accessToken } = getTokens();
  const headers = new Headers(options.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  const res = await fetchOrThrow(`${API_BASE_URL}${path}`, { ...options, headers });

  if (res.status === 401 && !_retried && accessToken) {
    const refreshed = await tryRefresh();
    if (refreshed) return apiFetchBlob(path, options, true);
    clearTokens();
  }

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body);
  }

  return res.blob();
}
