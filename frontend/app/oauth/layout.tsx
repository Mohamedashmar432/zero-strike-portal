import { ThinkShieldLogo } from "@/components/brand/logo";

/** Shell for pages a signed-in user reaches from outside the app (an AI client's authorization redirect). */
export default function OAuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-canvas flex min-h-screen items-center justify-center px-5 py-12">
      <div className="w-full max-w-md space-y-5">
        <ThinkShieldLogo size="lg" />
        {children}
      </div>
    </div>
  );
}
