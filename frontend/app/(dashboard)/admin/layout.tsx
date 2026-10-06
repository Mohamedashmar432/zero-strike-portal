"use client";

import { ShieldAlert } from "lucide-react";
import Link from "next/link";
import { EmptyState } from "@/components/common/empty-state";
import { Button } from "@/components/ui/button";
import { useHasRole } from "@/lib/hooks/use-has-role";

/**
 * One guard for every /admin page. A member who opens an admin URL directly gets a readable
 * refusal instead of an empty shell of "—" values, and the page's own queries never mount, so
 * no admin endpoint is asked (and 403s) on their behalf. Client-side only: the backend's
 * require_admin is what actually enforces access.
 */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const isAdmin = useHasRole("admin");
  if (isAdmin) return <>{children}</>;
  return (
    <div className="space-y-4">
      <EmptyState
        icon={ShieldAlert}
        title="Admins only"
        description="This page is for portal admins. Ask an admin if you need access."
      />
      <div className="flex justify-center">
        <Button variant="outline" nativeButton={false} render={<Link href="/dashboard" />}>
          Back to Dashboard
        </Button>
      </div>
    </div>
  );
}
