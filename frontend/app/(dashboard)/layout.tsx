"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { useAuth } from "@/providers/auth-provider";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, isAuthenticating, isRestoringSession } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isAuthenticating && !isRestoringSession && !user) router.replace("/login");
  }, [user, isAuthenticating, isRestoringSession, router]);

  if (!user) return null;

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex flex-1 flex-col">
        <Topbar />
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
