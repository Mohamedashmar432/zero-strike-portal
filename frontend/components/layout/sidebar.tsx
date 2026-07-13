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
import { cn, getInitials } from "@/lib/utils";
import { useAuth } from "@/providers/auth-provider";
import { adminLinks, mainLinks, settingsLinks } from "./nav-links";

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();

  async function handleLogout() {
    await logout();
    router.push("/login");
  }

  return (
    <aside className="hidden w-56 shrink-0 border-r border-border bg-card/40 md:flex md:flex-col">
      <div className="px-4 py-4">
        <span className="font-mono text-sm font-semibold tracking-tight">
          zero<span className="text-brand">strike</span>
        </span>
      </div>
      <nav className="flex-1 space-y-1 px-2">
        {mainLinks.map((link) => (
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
        <div className="px-3 pt-4 pb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Settings
        </div>
        {settingsLinks.map((link) => (
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
      </nav>
      <div className="border-t border-border p-2">
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <button className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left hover:bg-accent">
                <Avatar size="sm">
                  <AvatarFallback>{getInitials(user?.name ?? user?.email ?? "?")}</AvatarFallback>
                </Avatar>
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-sm font-medium text-foreground">{user?.name ?? "…"}</span>
                  <span className="truncate text-xs text-muted-foreground">{user?.email}</span>
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
