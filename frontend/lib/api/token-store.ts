// In-memory only — never localStorage. Lost on page reload by design; the
// user just logs in again. Avoids XSS-exfiltratable persisted tokens.
let accessToken: string | null = null;
let refreshToken: string | null = null;

export function getTokens() {
  return { accessToken, refreshToken };
}

export function setTokens(tokens: { accessToken: string; refreshToken: string }) {
  accessToken = tokens.accessToken;
  refreshToken = tokens.refreshToken;
}

export function clearTokens() {
  accessToken = null;
  refreshToken = null;
}
