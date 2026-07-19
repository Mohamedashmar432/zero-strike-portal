"use client";

import { Bell, PanelLeftClose, PanelLeftOpen, Search, Settings } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { RequireRole } from "@/components/auth/require-role";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { cn, getInitials } from "@/lib/utils";
import { useAuth } from "@/providers/auth-provider";
import { adminLinks, mainLinks } from "./nav-links";

const rowClass =
  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground";

export function Sidebar({ pinned, onTogglePin }: { pinned: boolean; onTogglePin: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const [search, setSearch] = useState("");

  // Labels/inputs are always visible when pinned; otherwise they fade in only on hover (opacity,
  // not display, so expanding never reflows the icon column).
  const labelClass = cn(
    "truncate whitespace-nowrap transition-opacity duration-150",
    pinned ? "opacity-100" : "opacity-0 group-hover:opacity-100"
  );

  async function handleLogout() {
    await logout();
    router.push("/login");
  }

  function handleSearch(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    router.push(search.trim() ? `/projects?q=${encodeURIComponent(search.trim())}` : "/projects");
  }

  return (
    <aside
      className={cn(
        "group fixed inset-y-0 left-0 z-40 hidden flex-col overflow-hidden border-r border-sidebar-border bg-sidebar py-4 text-sidebar-foreground shadow-2xl shadow-black/40 transition-[width] duration-200 md:flex",
        pinned ? "w-64" : "w-16 hover:w-64"
      )}
    >
      {/* Logo + top icon controls (pin / notifications / theme) */}
      <div className="mb-5 px-3">
        <div className="flex items-center gap-2 px-1">
          <span className="text-xl font-bold tracking-tight text-sidebar-primary">Z</span>
          <span className={cn("text-lg font-bold leading-none tracking-tight", labelClass)}>
            <span className="text-sidebar-primary">ero</span>Strike
          </span>
        </div>
        <div className={cn("mt-3 flex gap-1", pinned ? "flex-row" : "flex-col group-hover:flex-row")}>
          <Button
            variant="ghost"
            size="icon"
            aria-label={pinned ? "Unpin sidebar" : "Pin sidebar open"}
            title={pinned ? "Unpin (auto-collapse)" : "Pin sidebar open"}
            onClick={onTogglePin}
          >
            {pinned ? <PanelLeftClose /> : <PanelLeftOpen />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Notifications"
            className="relative"
            onClick={() => toast.info("No new notifications")}
          >
            <Bell />
            <span className="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-destructive" />
          </Button>
          <ThemeToggle />
        </div>
      </div>

      {/* Search */}
      <form onSubmit={handleSearch} className="relative mb-4 px-3">
        <button
          type="submit"
          aria-label="Search"
          className="absolute left-6 top-1/2 -translate-y-1/2 text-sidebar-foreground/70"
        >
          <Search className="size-[18px]" />
        </button>
        <input
          id="sidebar-search"
          name="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search…"
          className={cn(
            "w-full rounded-lg bg-sidebar-accent/40 py-2 pl-9 pr-2 text-sm text-sidebar-foreground placeholder:text-sidebar-foreground/40 outline-none focus:bg-sidebar-accent",
            labelClass
          )}
        />
      </form>

      <nav className="flex-1 space-y-1 px-3">
        {mainLinks.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={cn(
              rowClass,
              pathname?.startsWith(link.href) && "bg-sidebar-accent font-semibold text-sidebar-foreground"
            )}
          >
            <link.icon className="size-[18px] shrink-0" />
            <span className={labelClass}>{link.label}</span>
          </Link>
        ))}
        <RequireRole role="admin">
          <div
            className={cn(
              "px-3 pt-4 pb-1 text-xs font-semibold tracking-widest text-sidebar-foreground/40 uppercase",
              labelClass
            )}
          >
            Admin
          </div>
          {adminLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={cn(
                rowClass,
                pathname?.startsWith(link.href) && "bg-sidebar-accent font-semibold text-sidebar-foreground"
              )}
            >
              <link.icon className="size-[18px] shrink-0" />
              <span className={labelClass}>{link.label}</span>
            </Link>
          ))}
        </RequireRole>
        <Link
          href="/settings/profile"
          className={cn(
            rowClass,
            pathname?.startsWith("/settings") && "bg-sidebar-accent font-semibold text-sidebar-foreground"
          )}
        >
          <Settings className="size-[18px] shrink-0" />
          <span className={labelClass}>Settings</span>
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
                <span className={cn("flex min-w-0 flex-1 flex-col", labelClass)}>
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
