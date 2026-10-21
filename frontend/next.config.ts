import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  async redirects() {
    // MCP access and connected apps now live under Settings > Integrations. Not permanent (308): the
    // browser would cache it, and these paths may be reused.
    return [
      { source: "/admin/mcp", destination: "/settings/integrations/mcp", permanent: false },
      { source: "/settings/connected-apps", destination: "/settings/integrations/mcp", permanent: false },
    ];
  },
  async headers() {
    // The OAuth consent page grants an AI client access to the user's data: never let another
    // site frame it and overlay the Approve button.
    return [
      {
        source: "/oauth/:path*",
        headers: [
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};

export default nextConfig;
