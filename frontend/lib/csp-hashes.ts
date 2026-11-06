/**
 * Hashes of the inline <style> elements third-party code injects at import time, which cannot carry
 * the request nonce. Allowed by hash in proxy.ts's style-src; csp-hashes.test.ts fails when the
 * library's CSS changes, so an upgrade cannot silently leave its styles blocked.
 *
 * sonner (toasts) builds its <style> by appending an EMPTY element and then filling it in, and the
 * browser checks both states -- hence the empty-string hash as well. An empty <style> does nothing.
 */
export const SONNER_STYLE_HASH = "sha256-CIxDM5jnsGiKqXs2v7NKCY5MzdR9gu6TtiMJrDw29AY=";
export const EMPTY_STYLE_HASH = "sha256-47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=";
