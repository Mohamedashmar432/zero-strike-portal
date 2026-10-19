/**
 * A post-login destination taken from the URL, or null when it is not a plain same-origin path.
 * Only relative paths survive: "//evil.example", "/\evil.example", "https://..." and "javascript:..."
 * all fail, so `?next=` can never turn the login page into an open redirect.
 */
export function safeNextPath(raw: string | null | undefined): string | null {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return null;
  for (const ch of raw) {
    const code = ch.charCodeAt(0);
    if (code <= 0x1f || code === 0x7f || ch === "\\") return null;
  }
  try {
    const base = "http://same-origin.invalid";
    const url = new URL(raw, base);
    if (url.origin !== base) return null;
    return url.pathname + url.search + url.hash;
  } catch {
    return null;
  }
}
