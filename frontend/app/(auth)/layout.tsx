import { ZeroStrikeLogo } from "@/components/brand/logo";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="flex justify-center pb-2">
          <ZeroStrikeLogo size="lg" animated />
        </div>
        {children}
      </div>
    </div>
  );
}
