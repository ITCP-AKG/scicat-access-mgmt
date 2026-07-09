// Typed fetch wrapper for the backend /api/v1 and SciCat login (T013).

const TOKEN_KEY = 'scicat.token';

// When the app is served under a sub-path (prod, e.g. /access-mgmt), the backend is
// reached at `${BACKEND_BASE}/api/v1/...` and Traefik strips the prefix back to /api/v1.
// Empty in dev, where the Vite proxy forwards /api/v1 straight to the backend.
const BACKEND_BASE = (import.meta.env.VITE_BACKEND_BASE as string) || '';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
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
  if (resp.status === 204) return undefined as T;
  const text = await resp.text();
  const data = text ? JSON.parse(text) : undefined;
  if (!resp.ok) {
    const detail = (data && (data.detail || data.message)) || resp.statusText;
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

// SciCat login — exchanges username/password for a JWT used against the backend.
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
