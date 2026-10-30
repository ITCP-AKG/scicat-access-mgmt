// Typed fetch wrapper for the backend /api/v1 and SciCat login (T013).

const TOKEN_KEY = 'scicat.token';
// catorga_frontend's session (same origin in production): {token, expiresAt, username, userId}.
// Reusing it lets users who signed in to catorga — including via SSO/OIDC — skip the login.
export const CATORGA_SESSION_KEY = 'scicat_auth_token';
// The catorga token this app must not adopt again (signed out of here, or rejected). Only
// that one token: a later catorga sign-in brings a new token, which is adopted as usual.
const SKIP_CATORGA_KEY = 'access.skipCatorgaToken';
const LEGACY_SKIP_KEY = 'access.skipCatorgaSession'; // older all-or-nothing flag
localStorage.removeItem(LEGACY_SKIP_KEY);

// When the app is served under a sub-path (prod, e.g. /access-mgmt), the backend is
// reached at `${BACKEND_BASE}/api/v1/...` and Traefik strips the prefix back to /api/v1.
// Empty in dev, where the Vite proxy forwards /api/v1 straight to the backend.
const BACKEND_BASE = (import.meta.env.VITE_BACKEND_BASE as string) || '';

function catorgaToken(): string | null {
  try {
    const raw = localStorage.getItem(CATORGA_SESSION_KEY);
    if (!raw) return null;
    const stored = JSON.parse(raw) as { token?: unknown; expiresAt?: unknown };
    if (typeof stored.token !== 'string') return null;
    if (typeof stored.expiresAt === 'string' && Date.parse(stored.expiresAt) <= Date.now()) return null;
    if (stored.token === localStorage.getItem(SKIP_CATORGA_KEY)) return null;
    return stored.token;
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY) ?? catorgaToken();
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

/** Drop one token: our own login is forgotten, a catorga session is no longer adopted. */
function dropToken(token: string): void {
  if (localStorage.getItem(TOKEN_KEY) === token) localStorage.removeItem(TOKEN_KEY);
  else localStorage.setItem(SKIP_CATORGA_KEY, token);
}

/** Sign out of this app (catorga itself stays signed in). */
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
  const catorga = catorgaToken();
  if (catorga) localStorage.setItem(SKIP_CATORGA_KEY, catorga);
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

let onUnauthorized: (() => void) | null = null;

/** Called when the backend rejects the session token (HTTP 401). */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = getToken();
  const resp = await fetch(`${BACKEND_BASE}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (resp.status === 401 && token) {
    // 401 means SciCat rejected the token (an outage answers 503): that session is over,
    // though another one (our own login rejected, a live catorga session) may remain.
    dropToken(token);
    onUnauthorized?.();
  }
  if (resp.status === 204) return undefined as T;
  const text = await resp.text();
  let data: unknown;
  try {
    data = text ? JSON.parse(text) : undefined;
  } catch {
    data = undefined;
  }
  if (!resp.ok) {
    const parsed = data as { detail?: unknown; message?: unknown } | undefined;
    const detail = (parsed && (parsed.detail || parsed.message)) || resp.statusText;
    throw new ApiError(resp.status, typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return data as T;
}

export const api = {
  get: <T>(p: string) => request<T>('GET', p),
  post: <T>(p: string, b?: unknown) => request<T>('POST', p, b),
  patch: <T>(p: string, b?: unknown) => request<T>('PATCH', p, b),
  del: <T>(p: string) => request<T>('DELETE', p),
};

// SciCat login of a functional account — exchanges credentials for a JWT used against the
// backend. University (KIT) users sign in to catorga instead, whose session is adopted.
export async function scicatLogin(username: string, password: string): Promise<string> {
  const resp = await fetch('/api/v3/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!resp.ok) throw new ApiError(resp.status, 'SciCat login failed');
  const data = await resp.json();
  return data.access_token || data.id;
}
