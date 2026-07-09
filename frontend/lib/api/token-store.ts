// Access token is in-memory only. Refresh token lives in sessionStorage so a
// reload or hard navigation doesn't force re-login — tab-scoped, cleared on
// tab close. auth-provider uses it to silently re-issue an access token on
// mount via the existing refresh-rotation flow.
const REFRESH_KEY = "zerostrike_refresh_token";

let accessToken: string | null = null;

export function getTokens() {
  const refreshToken = typeof sessionStorage !== "undefined" ? sessionStorage.getItem(REFRESH_KEY) : null;
  return { accessToken, refreshToken };
}

export function setTokens(tokens: { accessToken: string; refreshToken: string }) {
  accessToken = tokens.accessToken;
  sessionStorage.setItem(REFRESH_KEY, tokens.refreshToken);
}

export function clearTokens() {
  accessToken = null;
  sessionStorage.removeItem(REFRESH_KEY);
}
