"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import * as authApi from "@/lib/api/auth";
import { tryRefresh } from "@/lib/api/client";
import { clearTokens, getTokens, setTokens } from "@/lib/api/token-store";
import { updateMyProfile } from "@/lib/api/users";

type AuthContextValue = {
  user: authApi.User | null;
  isAuthenticating: boolean;
  isRestoringSession: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name: string) => Promise<void>;
  logout: () => Promise<void>;
  // TODO: drop the string branch once settings/profile/page.tsx passes {name, email} directly
  updateProfile: (payload: string | { name?: string; email?: string }) => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<authApi.User | null>(null);
  const [isAuthenticating, setIsAuthenticating] = useState(false);
  const [isRestoringSession, setIsRestoringSession] = useState(true);

  // Access tokens are in-memory only; the refresh token survives in
  // sessionStorage (see token-store.ts) so a reload/hard nav can silently
  // re-issue an access token instead of forcing the user back to /login.
  useEffect(() => {
    (async () => {
      const { refreshToken } = getTokens();
      if (refreshToken && (await tryRefresh())) {
        try {
          setUser(await authApi.getMe());
        } catch {
          clearTokens();
        }
      } else if (refreshToken) {
        clearTokens();
      }
      setIsRestoringSession(false);
    })();
  }, []);

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

  async function updateProfile(payload: string | { name?: string; email?: string }) {
    // TODO: drop the string branch once settings/profile/page.tsx passes {name, email} directly
    setUser(await updateMyProfile(typeof payload === "string" ? { name: payload } : payload));
  }

  return (
    <AuthContext.Provider
      value={{ user, isAuthenticating, isRestoringSession, login, register, logout, updateProfile }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
