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
      {/* Desktop leaves room for the rail; pinned reserves the full width, unpinned just the icons.
          `app-canvas` lays a 22px dot grid under the content — panels need something
          to sit on, and a flat fill is the flattest possible generic-UI tell. */}
      <main
        className={cn(
          "app-canvas min-h-screen p-6 pt-16 transition-[margin] duration-200 md:pt-8 md:px-8",
          pinned ? "md:ml-60" : "md:ml-16"
        )}
      >
        {/* Content is capped and centred inside whatever space the rail leaves.
            Without this it stretched edge-to-edge, so on a wide window the page
            read as pushed against the right side rather than composed, and
            tables grew to absurd line lengths. mx-auto keeps the remaining
            gutter even on both sides. */}
        <div className="mx-auto w-full max-w-[1680px]">{children}</div>
      </main>
    </div>
  );
}
