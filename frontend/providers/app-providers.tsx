"use client";

import { ThemeProvider } from "next-themes";
import type { ReactNode } from "react";
import { z } from "zod";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthProvider } from "./auth-provider";
import { QueryProvider } from "./query-provider";

// zod probes `new Function("")` once to decide whether it may JIT-compile schemas. Under the portal's
// CSP (no 'unsafe-eval') that probe is blocked: harmless, but it logs a violation on every page load.
// jitless skips the probe; validation here is form-sized, so the speed-up is not missed.
z.config({ jitless: true });

export function AppProviders({ children, nonce }: { children: ReactNode; nonce?: string }) {
  return (
    // next-themes injects an inline script to set the theme class before first paint; under the
    // portal's CSP that script only runs when it carries the request's nonce.
    <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false} nonce={nonce}>
      <QueryProvider>
        <AuthProvider>
          <TooltipProvider>{children}</TooltipProvider>
          <Toaster richColors />
        </AuthProvider>
      </QueryProvider>
    </ThemeProvider>
  );
}
