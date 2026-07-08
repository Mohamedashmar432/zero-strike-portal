"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useAuth } from "@/providers/auth-provider";

const links = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/projects", label: "Projects" },
];

const adminLinks = [
  { href: "/admin/users", label: "Users" },
  { href: "/admin/audit-log", label: "Audit Log" },
];

export function Sidebar() {
  const pathname = usePathname();
  const { user } = useAuth();

  return (
    <aside className="hidden w-56 shrink-0 border-r border-border bg-card/40 md:flex md:flex-col">
      <div className="px-4 py-4">
        <span className="font-mono text-sm font-semibold tracking-tight">
          zero<span className="text-severity-high">strike</span>
        </span>
      </div>
      <nav className="flex-1 space-y-1 px-2">
        {links.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={cn(
              "block rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-foreground",
              pathname?.startsWith(link.href) && "bg-accent text-foreground"
            )}
          >
            {link.label}
          </Link>
        ))}
        {user?.role === "admin" && (
          <>
            <div className="px-3 pt-4 pb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Admin
            </div>
            {adminLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "block rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-foreground",
                  pathname?.startsWith(link.href) && "bg-accent text-foreground"
                )}
              >
                {link.label}
              </Link>
            ))}
          </>
        )}
      </nav>
    </aside>
  );
}
