import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import {
  clearToken,
  getToken,
  scicatLogin,
  setToken,
  setUnauthorizedHandler,
  type LoginMethod,
} from '../api/client';
import { UsersApi } from '../api/endpoints';
import type { Me } from '../api/types';

interface AuthState {
  me: Me | null;
  loading: boolean;
  login: (username: string, password: string, method?: LoginMethod) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    if (!getToken()) {
      setMe(null);
      setLoading(false);
      return;
    }
    try {
      setMe(await UsersApi.me());
    } catch {
      clearToken();
      setMe(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    // Any 401 from the backend ends the session and returns to the login page.
    setUnauthorizedHandler(() => setMe(null));
    return () => setUnauthorizedHandler(null);
  }, []);

  async function login(username: string, password: string, method: LoginMethod = 'local') {
    const token = await scicatLogin(username, password, method);
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
