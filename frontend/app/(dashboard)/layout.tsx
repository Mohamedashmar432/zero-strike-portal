"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { MobileNav } from "@/components/layout/mobile-nav";
import { Sidebar } from "@/components/layout/sidebar";
import { cn } from "@/lib/utils";
import { useAuth } from "@/providers/auth-provider";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, isAuthenticating, isRestoringSession } = useAuth();
  const router = useRouter();
  // Pinned = sticky/always-expanded rail; unpinned = narrow rail that expands on hover.
  const [pinned, setPinned] = useState(false);

  useEffect(() => {
    if (!isAuthenticating && !isRestoringSession && !user) router.replace("/login");
  }, [user, isAuthenticating, isRestoringSession, router]);

  if (!user) return null;

  return (
    <div className="min-h-screen">
      <Sidebar pinned={pinned} onTogglePin={() => setPinned((p) => !p)} />
      {/* Mobile: the sidebar is hidden; a floating trigger opens the drawer nav. */}
      <div className="fixed left-3 top-3 z-50 md:hidden">
        <MobileNav />
      </div>
      {/* Desktop leaves room for the rail; pinned reserves the full width, unpinned just the icons. */}
      <main
        className={cn(
          "min-h-screen p-6 pt-16 transition-[margin] duration-200 md:pt-6",
          pinned ? "md:ml-64" : "md:ml-16"
        )}
      >
        {children}
      </main>
    </div>
  );
}
