"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Settings } from "lucide-react";
import { cn, getInitials } from "@/lib/utils";
import { useAuth } from "@/providers/auth-provider";
import { adminLinks, mainLinks } from "./nav-links";

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();

  async function handleLogout() {
    await logout();
    router.push("/login");
  }

  return (
    <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col overflow-y-auto border-r border-sidebar-border bg-sidebar py-6 text-sidebar-foreground shadow-[4px_0_24px_-6px_var(--primary)] md:flex">
      <div className="mb-8 px-6">
        <h1 className="text-xl font-bold tracking-tight">
          <span className="text-sidebar-primary">Zero</span>Strike
        </h1>
        <p className="mt-0.5 text-xs text-sidebar-foreground/60">Security Platform</p>
      </div>
      <nav className="flex-1 space-y-1 px-3">
        {mainLinks.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground",
              pathname?.startsWith(link.href) && "bg-sidebar-accent font-semibold text-sidebar-foreground"
            )}
          >
            <link.icon className="size-[18px]" />
            {link.label}
          </Link>
        ))}
        {user?.role === "admin" && (
          <>
            <div className="px-3 pt-4 pb-1 text-xs font-semibold tracking-widest text-sidebar-foreground/40 uppercase">
              Admin
            </div>
            {adminLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground",
                  pathname?.startsWith(link.href) && "bg-sidebar-accent font-semibold text-sidebar-foreground"
                )}
              >
                <link.icon className="size-[18px]" />
                {link.label}
              </Link>
            ))}
          </>
        )}
        <Link
          href="/settings/profile"
          className={cn(
            "flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground",
            pathname?.startsWith("/settings") && "bg-sidebar-accent font-semibold text-sidebar-foreground"
          )}
        >
          <Settings className="size-[18px]" />
          Settings
        </Link>
      </nav>
      <div className="mt-4 border-t border-sidebar-border p-3">
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <button className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left hover:bg-sidebar-accent">
                <Avatar size="sm">
                  <AvatarFallback>{getInitials(user?.name ?? user?.email ?? "?")}</AvatarFallback>
                </Avatar>
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-sm font-medium text-sidebar-foreground">{user?.name ?? "…"}</span>
                  <span className="truncate text-xs text-sidebar-foreground/50">{user?.email}</span>
                </span>
              </button>
            }
          />
          <DropdownMenuContent align="start" side="top">
            <DropdownMenuItem render={<Link href="/settings/profile">Profile settings</Link>} />
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onClick={handleLogout}>
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </aside>
  );
}
