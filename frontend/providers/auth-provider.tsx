"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import * as authApi from "@/lib/api/auth";
import { tryRefresh } from "@/lib/api/client";
import { SESSION_USER_KEY, clearTokens, getTokens, setTokens } from "@/lib/api/token-store";
import { updateMyProfile } from "@/lib/api/users";

type AuthContextValue = {
  user: authApi.User | null;
  isAuthenticating: boolean;
  isRestoringSession: boolean;
  login: (email: string, password: string, remember?: boolean) => Promise<void>;
  /** Resolves to the new account; a `pending` one is NOT signed in. */
  register: (email: string, password: string, name: string, inviteToken?: string | null) => Promise<authApi.User>;
  logout: () => Promise<void>;
  updateProfile: (payload: { name?: string }) => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<authApi.User | null>(null);
  const [isAuthenticating, setIsAuthenticating] = useState(false);
  const [isRestoringSession, setIsRestoringSession] = useState(true);

  // Access tokens are in-memory only; the browser-wide refresh token (see token-store.ts) lets a
  // reload or a new tab silently re-issue one instead of forcing the user back to /login.
  useEffect(() => {
    (async () => {
      if (getTokens().refreshToken && (await tryRefresh())) {
        try {
          setUser(await authApi.getMe());
        } catch {
          clearTokens();
        }
      } else {
        clearTokens();
      }
      setIsRestoringSession(false);
    })();
  }, []);

  // One session per browser: when another tab signs in as someone else or signs out, this tab
  // follows. A full navigation (not a router push) drops every cached query, so the previous user's
  // data can never render under the new one.
  useEffect(() => {
    function onStorage(e: StorageEvent) {
      if (e.key !== SESSION_USER_KEY && e.key !== null) return;
      const signedInAs = localStorage.getItem(SESSION_USER_KEY);
      if (signedInAs === (user?.id ?? null)) return;
      window.location.assign(signedInAs ? "/dashboard" : "/login");
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [user?.id]);

  async function login(email: string, password: string, remember = false) {
    setIsAuthenticating(true);
    try {
      const tokens = await authApi.login(email, password, remember);
      // Signing in replaces whatever session this browser held; revoke it rather than orphan it.
      const { refreshToken: previous } = getTokens();
      if (previous) await authApi.logout(previous).catch(() => undefined);
      setTokens({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token, remember });
      const me = await authApi.getMe();
      localStorage.setItem(SESSION_USER_KEY, me.id);
      setUser(me);
    } finally {
      setIsAuthenticating(false);
    }
  }

  async function register(email: string, password: string, name: string, inviteToken?: string | null) {
    setIsAuthenticating(true);
    try {
      const created = await authApi.register(email, password, name, inviteToken);
      if (created.approval_status === "pending") return created;
      await login(email, password);
      return created;
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

  async function updateProfile(payload: { name?: string }) {
    setUser(await updateMyProfile(payload));
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
