export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <span className="text-2xl font-bold tracking-tight text-foreground">
            <span className="text-primary">Zero</span>Strike
          </span>
          <p className="mt-1 text-xs text-muted-foreground">Security Platform</p>
        </div>
        {children}
      </div>
    </div>
  );
}
