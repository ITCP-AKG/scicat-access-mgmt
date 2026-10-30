import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import {
  ApiError,
  CATORGA_SESSION_KEY,
  clearToken,
  getToken,
  scicatLogin,
  setToken,
  setUnauthorizedHandler,
} from '../api/client';
import { UsersApi } from '../api/endpoints';
import type { Me } from '../api/types';

interface AuthState {
  me: Me | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const inflight = useRef<Promise<void> | null>(null);

  // The client drops a token SciCat rejects (401), so on a 401 try the next one: our own
  // login first, then the catorga session. Any other failure (e.g. SciCat down, 503)
  // keeps the token for the next attempt.
  function refresh(): Promise<void> {
    inflight.current ??= (async () => {
      let next: Me | null = null;
      for (let attempt = 0; attempt < 2 && getToken(); attempt++) {
        try {
          next = await UsersApi.me();
          break;
        } catch (e) {
          if (!(e instanceof ApiError && e.status === 401)) break;
        }
      }
      setMe(next);
      setLoading(false);
    })().finally(() => {
      inflight.current = null;
    });
    return inflight.current;
  }

  useEffect(() => {
    void refresh();
    // A 401 from the backend ends that session; fall back to another one, or the login page.
    setUnauthorizedHandler(() => {
      setLoading(true);
      void refresh();
    });
    // Follow catorga sign-ins and sign-outs made in other tabs of the same origin.
    const onStorage = (e: StorageEvent) => {
      if (e.key === CATORGA_SESSION_KEY || e.key === null) void refresh();
    };
    window.addEventListener('storage', onStorage);
    return () => {
      setUnauthorizedHandler(null);
      window.removeEventListener('storage', onStorage);
    };
  }, []);

  async function login(username: string, password: string) {
    const token = await scicatLogin(username, password);
    setToken(token);
    setLoading(true);
    await refresh();
  }

  function logout() {
    clearToken();
    setMe(null);
  }

  return (
    <AuthContext.Provider value={{ me, loading, login, logout }}>{children}</AuthContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
