export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <span className="font-mono text-lg font-semibold tracking-tight text-foreground">
            zero<span className="text-brand">strike</span>
          </span>
        </div>
        {children}
      </div>
    </div>
  );
}
