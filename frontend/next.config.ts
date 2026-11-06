import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Don't advertise the framework on every response.
  poweredByHeader: false,
  async redirects() {
    // MCP access and connected apps now live under Settings > Integrations. Not permanent (308): the
    // browser would cache it, and these paths may be reused.
    return [
      { source: "/admin/mcp", destination: "/settings/integrations/mcp", permanent: false },
      { source: "/settings/connected-apps", destination: "/settings/integrations/mcp", permanent: false },
    ];
  },
  async headers() {
    // Every route: nothing in the portal is meant to be framed (the OAuth consent page grants an AI
    // client access to the user's data, and another site must never overlay its Approve button).
    // CSP is deliberately limited to directives that cannot break Next's inline bootstrap scripts;
    // a script-src policy needs per-request nonces and is a separate change.
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Content-Security-Policy",
            value: "frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
          },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
