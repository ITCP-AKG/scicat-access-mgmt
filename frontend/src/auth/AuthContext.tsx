import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { clearToken, getToken, scicatLogin, setToken } from '../api/client';
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
