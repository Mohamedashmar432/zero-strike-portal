// One session per browser, shared by every tab. Access token is in-memory only (per tab, re-issued
// from the refresh token on load). Where the refresh token lives depends on "Remember me":
//   - ticked:   localStorage — survives a browser restart; the server ends it 7 days after sign-in.
//   - unticked: a session cookie — shared by tabs, gone when the browser closes (and the server
//               ends it after 12 hours regardless).
// Either way the server, not this file, owns the lifetime: rotation never extends it.
const REFRESH_KEY = "zerostrike_refresh_token";
// Non-secret marker of WHO is signed in. Every tab listens for it changing (auth-provider), so a
// sign-in or sign-out in one tab moves every other tab with it instead of leaving two users open.
export const SESSION_USER_KEY = "zerostrike_session_user";

let accessToken: string | null = null;

function readCookie(): string | null {
  const hit = document.cookie.split("; ").find((c) => c.startsWith(`${REFRESH_KEY}=`));
  return hit ? decodeURIComponent(hit.slice(REFRESH_KEY.length + 1)) : null;
}

function writeCookie(value: string | null) {
  const secure = location.protocol === "https:" ? "; Secure" : "";
  document.cookie = value
    ? `${REFRESH_KEY}=${encodeURIComponent(value)}; Path=/; SameSite=Strict${secure}`
    : `${REFRESH_KEY}=; Path=/; Max-Age=0; SameSite=Strict${secure}`;
}

export function getTokens() {
  if (typeof window === "undefined") return { accessToken, refreshToken: null };
  return { accessToken, refreshToken: localStorage.getItem(REFRESH_KEY) ?? readCookie() };
}

/** `remember` is set on sign-in; a rotation omits it and keeps the token where it already lives. */
export function setTokens(tokens: { accessToken: string; refreshToken: string; remember?: boolean }) {
  accessToken = tokens.accessToken;
  const remember = tokens.remember ?? localStorage.getItem(REFRESH_KEY) !== null;
  if (remember) {
    writeCookie(null);
    localStorage.setItem(REFRESH_KEY, tokens.refreshToken);
  } else {
    localStorage.removeItem(REFRESH_KEY);
    writeCookie(tokens.refreshToken);
  }
}

export function clearTokens() {
  accessToken = null;
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(SESSION_USER_KEY);
  writeCookie(null);
}
