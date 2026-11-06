import { NextResponse, type NextRequest } from "next/server";
import { EMPTY_STYLE_HASH, SONNER_STYLE_HASH } from "@/lib/csp-hashes";

/**
 * Per-request Content-Security-Policy with a script/style nonce (Next.js "Proxy", formerly middleware).
 *
 * Why a nonce and not 'unsafe-inline': Next's bootstrap and streaming scripts are inline, so a
 * script-src without either would blank the app. A nonce lets exactly those scripts run and nothing an
 * injected tag could add (strict-dynamic then lets the nonce'd bundle load its own chunks). Next reads
 * the nonce back out of this header while rendering and stamps it on its own tags; the root layout
 * opts every page into dynamic rendering, because a statically built page has no request to carry one.
 *
 * style-src-attr is the one deliberate 'unsafe-inline': the UI primitives (popovers, tooltips, charts,
 * progress bars) position and colour themselves with style="" attributes, which a nonce cannot cover.
 * Attribute styles cannot run script; <style> elements stay nonce-only.
 */
function apiOrigin(): string | null {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!base) return null;
  try {
    return new URL(base).origin; // absolute (cross-origin backend); a relative "/api/v1" throws
  } catch {
    return null; // same-origin, already covered by 'self'
  }
}

export function proxy(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const isDev = process.env.NODE_ENV === "development";
  const api = apiOrigin();

  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    // sonner injects its own <style> at import time and cannot take a nonce; allowed by hash (see
    // lib/csp-hashes.ts, which has a test that fails if the hash goes stale).
    `style-src 'self' ${isDev ? "'unsafe-inline'" : `'nonce-${nonce}' '${SONNER_STYLE_HASH}' '${EMPTY_STYLE_HASH}'`}`,
    "style-src-attr 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self' data:",
    `connect-src 'self'${api ? ` ${api}` : ""}`,
    "form-action 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "object-src 'none'",
    // Dev serves over http://localhost, where upgrading every request to https would break it.
    ...(isDev ? [] : ["upgrade-insecure-requests"]),
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: [
    {
      source: "/((?!_next/static|_next/image|favicon.ico|icon.svg).*)",
      // Prefetches are answered without a body that needs a nonce.
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
