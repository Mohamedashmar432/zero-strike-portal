import { apiFetch } from "./client";

export type User = {
  id: string;
  email: string;
  name: string;
  role: "admin" | "user";
  is_active: boolean;
};

export type TokenPair = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
};

export function login(email: string, password: string) {
  return apiFetch<TokenPair>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function register(email: string, password: string, name: string) {
  return apiFetch<User>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, name }),
  });
}

export function logout(refreshToken: string) {
  return apiFetch<void>("/auth/logout", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
}

export function getMe() {
  return apiFetch<User>("/auth/me");
}
