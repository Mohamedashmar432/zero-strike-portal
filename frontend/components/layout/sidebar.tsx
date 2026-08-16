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
import { ZeroStrikeLogoIcon } from "@/components/brand/logo";
import { cn, getInitials } from "@/lib/utils";
import { useAuth } from "@/providers/auth-provider";
import { adminLinks, mainLinks } from "./nav-links";

export function Sidebar({ pinned, onTogglePin }: { pinned: boolean; onTogglePin: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const [search, setSearch] = useState("");

  const labelClass = cn(
    "truncate whitespace-nowrap transition-opacity duration-150 text-xs",
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
        "group fixed inset-y-0 left-0 z-40 hidden flex-col overflow-hidden border-r border-sidebar-border bg-sidebar py-3 text-sidebar-foreground transition-[width] duration-200 md:flex",
        pinned ? "w-60" : "w-16 hover:w-60"
      )}
    >
      {/* Brand Header */}
      <div className="mb-3 px-2.5">
        <div className="flex items-center gap-3 px-1 py-1">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-lg p-0.5 shadow-sm transition-transform duration-200 hover:scale-105">
            <ZeroStrikeLogoIcon className="size-7" />
          </div>
          <div className={cn("flex flex-col min-w-0", labelClass)}>
            <span className="text-sm font-bold tracking-tight text-sidebar-foreground leading-tight">
              Zero<span className="text-primary font-mono">Strike</span>
            </span>
            <span className="text-[9px] font-mono tracking-widest text-sidebar-foreground/50 uppercase">
              DevSecOps Platform
            </span>
          </div>
        </div>

        {/* Controls Row */}
        <div className={cn("mt-2.5 flex items-center justify-between border-b border-sidebar-border/60 pb-2 px-1", pinned ? "flex-row" : "flex-col group-hover:flex-row gap-1")}>
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={pinned ? "Unpin sidebar" : "Pin sidebar open"}
            title={pinned ? "Unpin (auto-collapse)" : "Pin sidebar open"}
            onClick={onTogglePin}
            className="text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent"
          >
            {pinned ? <PanelLeftClose className="size-4" /> : <PanelLeftOpen className="size-4" />}
          </Button>
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label="Notifications"
            className="relative text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent"
            onClick={() => toast.info("No new notifications")}
          >
            <Bell className="size-4" />
            <span className="absolute right-1 top-1 size-1.5 rounded-full bg-destructive" />
          </Button>
          <ThemeToggle />
        </div>
      </div>

      {/* Quick Search */}
      <form onSubmit={handleSearch} className="relative mb-3 px-2.5">
        <button
          type="submit"
          aria-label="Search"
          className="absolute left-5 top-1/2 -translate-y-1/2 text-sidebar-foreground/50 hover:text-sidebar-foreground"
        >
          <Search className="size-4" />
        </button>
        <input
          id="sidebar-search"
          name="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Jump to project…"
          className={cn(
            "w-full rounded-lg border border-sidebar-border/60 bg-sidebar-accent/30 py-1.5 pl-8 pr-2 text-xs text-sidebar-foreground placeholder:text-sidebar-foreground/40 outline-none focus:border-primary/50 focus:bg-sidebar-accent/60 transition-colors",
            labelClass
          )}
        />
      </form>

      {/* Navigation Groups */}
      <nav className="flex-1 space-y-1 overflow-y-auto px-2.5">
        <div
          className={cn(
            "px-2 pt-1 pb-1 text-[10px] font-semibold tracking-wider text-sidebar-foreground/40 uppercase font-mono",
            labelClass
          )}
        >
          Operations
        </div>
        {mainLinks.map((link) => {
          const isActive = pathname === link.href || (link.href !== "/dashboard" && pathname?.startsWith(link.href));
          return (
            <Link
              key={link.href}
              href={link.href}
              className={cn(
                "group/item relative flex h-9 items-center gap-3 rounded-lg px-2.5 text-xs font-medium text-sidebar-foreground/70 transition-all duration-150 hover:bg-sidebar-accent/80 hover:text-sidebar-foreground",
                isActive && "bg-sidebar-accent font-semibold text-sidebar-foreground shadow-xs shadow-black/20"
              )}
            >
              {isActive && (
                <span className="absolute left-0 top-1.5 bottom-1.5 w-1 rounded-r-full bg-primary" />
              )}
              <div className="flex size-6 shrink-0 items-center justify-center">
                <link.icon className={cn("size-4.5 transition-colors", isActive ? "text-primary" : "text-sidebar-foreground/60 group-hover/item:text-sidebar-foreground")} />
              </div>
              <span className={labelClass}>{link.label}</span>
            </Link>
          );
        })}

        <RequireRole role="admin">
          <div
            className={cn(
              "px-2 pt-3 pb-1 text-[10px] font-semibold tracking-wider text-sidebar-foreground/40 uppercase font-mono",
              labelClass
            )}
          >
            Administration
          </div>
          {adminLinks.map((link) => {
            const isActive = pathname?.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "group/item relative flex h-9 items-center gap-3 rounded-lg px-2.5 text-xs font-medium text-sidebar-foreground/70 transition-all duration-150 hover:bg-sidebar-accent/80 hover:text-sidebar-foreground",
                  isActive && "bg-sidebar-accent font-semibold text-sidebar-foreground shadow-xs shadow-black/20"
                )}
              >
                {isActive && (
                  <span className="absolute left-0 top-1.5 bottom-1.5 w-1 rounded-r-full bg-primary" />
                )}
                <div className="flex size-6 shrink-0 items-center justify-center">
                  <link.icon className={cn("size-4.5 transition-colors", isActive ? "text-primary" : "text-sidebar-foreground/60 group-hover/item:text-sidebar-foreground")} />
                </div>
                <span className={labelClass}>{link.label}</span>
              </Link>
            );
          })}
        </RequireRole>

        <div
          className={cn(
            "px-2 pt-3 pb-1 text-[10px] font-semibold tracking-wider text-sidebar-foreground/40 uppercase font-mono",
            labelClass
          )}
        >
          Workspace
        </div>
        <Link
          href="/settings/profile"
          className={cn(
            "group/item relative flex h-9 items-center gap-3 rounded-lg px-2.5 text-xs font-medium text-sidebar-foreground/70 transition-all duration-150 hover:bg-sidebar-accent/80 hover:text-sidebar-foreground",
            pathname?.startsWith("/settings") && "bg-sidebar-accent font-semibold text-sidebar-foreground shadow-xs shadow-black/20"
          )}
        >
          {pathname?.startsWith("/settings") && (
            <span className="absolute left-0 top-1.5 bottom-1.5 w-1 rounded-r-full bg-primary" />
          )}
          <div className="flex size-6 shrink-0 items-center justify-center">
            <Settings className={cn("size-4.5 transition-colors", pathname?.startsWith("/settings") ? "text-primary" : "text-sidebar-foreground/60 group-hover/item:text-sidebar-foreground")} />
          </div>
          <span className={labelClass}>Settings</span>
        </Link>
      </nav>

      {/* User Footer Profile */}
      <div className="mt-auto border-t border-sidebar-border/60 p-2">
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <button className="flex w-full items-center gap-2.5 rounded-lg p-1.5 text-left transition-colors hover:bg-sidebar-accent">
                <Avatar size="sm" className="border border-sidebar-border shrink-0">
                  <AvatarFallback className="bg-primary/20 text-xs font-medium text-primary">
                    {getInitials(user?.name ?? user?.email ?? "?")}
                  </AvatarFallback>
                </Avatar>
                <span className={cn("flex min-w-0 flex-1 flex-col", labelClass)}>
                  <span className="truncate text-xs font-semibold text-sidebar-foreground">{user?.name ?? "User"}</span>
                  <span className="truncate font-mono text-[10px] text-sidebar-foreground/50">{user?.email}</span>
                </span>
              </button>
            }
          />
          <DropdownMenuContent align="start" side="top" className="w-56">
            <DropdownMenuItem render={<Link href="/settings/profile">Profile settings</Link>} />
            <DropdownMenuItem render={<Link href="/settings/integrations">Integrations</Link>} />
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
