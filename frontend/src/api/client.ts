// Typed fetch wrapper for the backend /api/v1 and SciCat login (T013).

const TOKEN_KEY = 'scicat.token';
// catorga_frontend's session (same origin in production): {token, expiresAt, username, userId}.
// Reusing it lets users who signed in to catorga — including via SSO/OIDC — skip the login.
const CATORGA_SESSION_KEY = 'scicat_auth_token';
// Set on sign-out so the catorga session is not silently adopted again.
const SKIP_CATORGA_KEY = 'access.skipCatorgaSession';

// When the app is served under a sub-path (prod, e.g. /access-mgmt), the backend is
// reached at `${BACKEND_BASE}/api/v1/...` and Traefik strips the prefix back to /api/v1.
// Empty in dev, where the Vite proxy forwards /api/v1 straight to the backend.
const BACKEND_BASE = (import.meta.env.VITE_BACKEND_BASE as string) || '';

function catorgaToken(): string | null {
  if (localStorage.getItem(SKIP_CATORGA_KEY)) return null;
  try {
    const raw = localStorage.getItem(CATORGA_SESSION_KEY);
    if (!raw) return null;
    const stored = JSON.parse(raw) as { token?: unknown; expiresAt?: unknown };
    if (typeof stored.token !== 'string') return null;
    if (typeof stored.expiresAt === 'string' && Date.parse(stored.expiresAt) <= Date.now()) return null;
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
  localStorage.removeItem(SKIP_CATORGA_KEY);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.setItem(SKIP_CATORGA_KEY, '1');
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
    // 401 means SciCat rejected the token (an outage answers 503): the session is over.
    clearToken();
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

export type LoginMethod = 'local' | 'ldap';

// SciCat login — exchanges credentials for a JWT used against the backend. `local` is for
// SciCat functional accounts, `ldap` for university (AD/LDAP) accounts.
export async function scicatLogin(
  username: string,
  password: string,
  method: LoginMethod = 'local',
): Promise<string> {
  const resp = await fetch(`/api/v3/auth/${method === 'ldap' ? 'ldap' : 'login'}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!resp.ok) throw new ApiError(resp.status, 'SciCat login failed');
  const data = await resp.json();
  return data.access_token || data.id;
}
