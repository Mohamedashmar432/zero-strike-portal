import Link from "next/link";

// Replaces Next's built-in 404, whose page ships an inline <style> block with no nonce. The portal's
// CSP (proxy.ts) blocks that block, so the default page rendered unstyled and logged a violation.
export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-3 p-8 text-center">
      <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">404</p>
      <h1 className="font-mono text-xl font-semibold">Page not found</h1>
      <Link href="/dashboard" className="text-sm text-primary underline-offset-4 hover:underline">
        Back to dashboard
      </Link>
    </main>
  );
}
