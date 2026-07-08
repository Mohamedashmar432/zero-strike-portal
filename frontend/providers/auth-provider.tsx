"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import * as authApi from "@/lib/api/auth";
import { clearTokens, getTokens, setTokens } from "@/lib/api/token-store";
import { updateMyProfile } from "@/lib/api/users";

type AuthContextValue = {
  user: authApi.User | null;
  isAuthenticating: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name: string) => Promise<void>;
  logout: () => Promise<void>;
  updateProfile: (name: string) => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

// ponytail: tokens are in-memory only (see token-store.ts), so a page reload
// always requires re-login — no session restore on mount. Upgrade path: move
// the refresh token to an httpOnly cookie set by the backend (see plan §7)
// once that backend work is prioritized.
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<authApi.User | null>(null);
  const [isAuthenticating, setIsAuthenticating] = useState(false);

  async function login(email: string, password: string) {
    setIsAuthenticating(true);
    try {
      const tokens = await authApi.login(email, password);
      setTokens({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token });
      setUser(await authApi.getMe());
    } finally {
      setIsAuthenticating(false);
    }
  }

  async function register(email: string, password: string, name: string) {
    setIsAuthenticating(true);
    try {
      await authApi.register(email, password, name);
      await login(email, password);
    } finally {
      setIsAuthenticating(false);
    }
  }

  async function logout() {
    const { refreshToken } = getTokens();
    if (refreshToken) {
      await authApi.logout(refreshToken).catch(() => undefined);
    }
    clearTokens();
    setUser(null);
  }

  async function updateProfile(name: string) {
    setUser(await updateMyProfile(name));
  }

  return (
    <AuthContext.Provider value={{ user, isAuthenticating, login, register, logout, updateProfile }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
