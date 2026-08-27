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

/**
 * Nav item. Active state is a square-cut lime marker flush against the rail's
 * left edge, running the item's full height — a channel-selected indicator on a
 * mixing desk. The old version used a rounded pill marker inset from the edge,
 * which reads as decoration; flush to the edge reads as a mechanism.
 */
function NavItem({
  href,
  label,
  icon: Icon,
  isActive,
  labelClass,
}: {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  isActive: boolean;
  labelClass: string;
}) {
  return (
    <Link
      href={href}
      aria-current={isActive ? "page" : undefined}
      className={cn(
        // Full-bleed rack row: no horizontal margin, no rounded corners, so the
        // active marker can sit flush against the rail edge and the hover fill
        // spans the whole unit.
        "group/item relative flex h-9 items-center gap-3 pl-3.5 pr-2.5 font-mono text-[13px] tracking-[-0.01em] text-sidebar-foreground/65 transition-colors duration-150",
        "hover:bg-sidebar-accent hover:text-sidebar-foreground",
        "focus-visible:outline-none focus-visible:-outline-offset-2 focus-visible:outline-2 focus-visible:outline-sidebar-ring/60",
        isActive && "bg-sidebar-accent font-semibold text-sidebar-foreground"
      )}
    >
      {isActive && <span className="absolute inset-y-0 left-0 w-[3px] bg-signal" />}
      <span className="flex size-5 shrink-0 items-center justify-center">
        <Icon
          className={cn(
            "size-4 transition-colors",
            isActive ? "text-signal" : "text-sidebar-foreground/55 group-hover/item:text-sidebar-foreground"
          )}
        />
      </span>
      <span className={labelClass}>{label}</span>
    </Link>
  );
}

export function Sidebar({ pinned, onTogglePin }: { pinned: boolean; onTogglePin: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const [search, setSearch] = useState("");

  const labelClass = cn(
    "truncate whitespace-nowrap transition-opacity duration-150",
    pinned ? "opacity-100" : "opacity-0 group-hover:opacity-100"
  );

  // Group headings must collapse their BOX in the icon rail, not just fade out —
  // opacity-0 left 17-33px of dead space between icon clusters.
  const groupLabelClass = (first: boolean) =>
    cn(
      "legend overflow-hidden truncate whitespace-nowrap px-3.5 text-sidebar-foreground/60 transition-all duration-150",
      pinned
        ? cn("h-4 opacity-100", first ? "pb-1.5" : "mt-4 pb-1.5")
        : cn(
            "h-0 opacity-0 group-hover:h-4 group-hover:pb-1.5 group-hover:opacity-100",
            !first && "group-hover:mt-4"
          )
    );

  async function handleLogout() {
    await logout();
    router.push("/login");
  }

  function handleSearch(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    router.push(search.trim() ? `/projects?q=${encodeURIComponent(search.trim())}` : "/projects");
  }

  const settingsActive = pathname?.startsWith("/settings") ?? false;

  return (
    <aside
      className={cn(
        "group fixed inset-y-0 left-0 z-40 hidden flex-col overflow-hidden border-r border-sidebar-border bg-sidebar py-3 text-sidebar-foreground transition-[width] duration-200 md:flex",
        pinned ? "w-60" : "w-16 hover:w-60"
      )}
    >
      {/* Brand */}
      <div className="mb-3 px-2.5">
        <div className="flex items-center gap-3 px-1">
          <div className="flex size-8 shrink-0 items-center justify-center text-sidebar-foreground">
            <ZeroStrikeLogoIcon className="size-[26px]" />
          </div>
          <div className={cn("flex min-w-0 flex-col gap-0.5", labelClass)}>
            <span className="font-mono text-sm font-bold leading-none tracking-[-0.04em] text-sidebar-foreground">
              ZeroStrike
            </span>
            <span className="legend text-sidebar-foreground/60">
              <span className="text-signal">{"//"}</span> SAST Control
            </span>
          </div>
        </div>

        {/* Rail controls */}
        <div
          className={cn(
            "mt-3 flex items-center gap-1 border-b border-sidebar-border pb-2.5",
            pinned ? "flex-row" : "flex-col group-hover:flex-row"
          )}
        >
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={pinned ? "Unpin sidebar" : "Pin sidebar open"}
            title={pinned ? "Unpin (auto-collapse)" : "Pin sidebar open"}
            onClick={onTogglePin}
            className="text-sidebar-foreground/55 hover:bg-sidebar-accent hover:text-sidebar-foreground"
          >
            {pinned ? <PanelLeftClose className="size-4" /> : <PanelLeftOpen className="size-4" />}
          </Button>
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label="Notifications"
            className="relative text-sidebar-foreground/55 hover:bg-sidebar-accent hover:text-sidebar-foreground"
            onClick={() => toast.info("No new notifications")}
          >
            <Bell className="size-4" />
            <span className="absolute right-0.5 top-0.5 size-1.5 rounded-full bg-signal" />
          </Button>
          <ThemeToggle />
        </div>
      </div>

      {/* Jump-to search */}
      <form onSubmit={handleSearch} className="relative mb-4 px-2.5">
        <button
          type="submit"
          aria-label="Search projects"
          className="absolute left-3.5 top-1/2 z-10 grid size-7 -translate-y-1/2 place-items-center rounded-sm text-sidebar-foreground/60 transition-colors hover:text-signal focus-visible:outline-2 focus-visible:outline-sidebar-ring/60"
        >
          <Search className="size-3.5" />
        </button>
        <input
          id="sidebar-search"
          name="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="jump to project…"
          className={cn(
            "w-full rounded-sm border border-sidebar-input bg-sidebar-accent/40 py-1.5 pl-7 pr-2 font-mono text-[12px] text-sidebar-foreground outline-none transition-colors",
            "placeholder:text-sidebar-foreground/60 focus:border-signal/50 focus:bg-sidebar-accent",
            labelClass
          )}
        />
      </form>

      {/* Navigation */}
      <nav className="flex-1 space-y-0.5 overflow-y-auto overflow-x-hidden">
        <div className={groupLabelClass(true)}>
          Operations
        </div>
        {mainLinks.map((link) => (
          <NavItem
            key={link.href}
            {...link}
            labelClass={labelClass}
            isActive={
              pathname === link.href ||
              (link.href !== "/dashboard" && (pathname?.startsWith(link.href) ?? false))
            }
          />
        ))}

        <RequireRole role="admin">
          <div className={groupLabelClass(false)}>
            Administration
          </div>
          {adminLinks.map((link) => (
            <NavItem
              key={link.href}
              {...link}
              labelClass={labelClass}
              isActive={pathname?.startsWith(link.href) ?? false}
            />
          ))}
        </RequireRole>

        <div className={groupLabelClass(false)}>
          Workspace
        </div>
        <NavItem
          href="/settings/profile"
          label="Settings"
          icon={Settings}
          isActive={settingsActive}
          labelClass={labelClass}
        />
      </nav>

      {/* Operator */}
      <div className="mt-auto border-t border-sidebar-border px-2.5 pt-2">
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <button className="flex w-full cursor-pointer items-center gap-2.5 rounded-sm p-1.5 text-left transition-colors hover:bg-sidebar-accent">
                <Avatar size="sm" className="shrink-0 rounded-sm border border-sidebar-border">
                  <AvatarFallback className="rounded-sm bg-signal/15 font-mono text-[11px] font-bold text-signal">
                    {getInitials(user?.name ?? user?.email ?? "?")}
                  </AvatarFallback>
                </Avatar>
                <span className={cn("flex min-w-0 flex-1 flex-col gap-0.5", labelClass)}>
                  <span className="truncate font-mono text-[12px] font-semibold text-sidebar-foreground">
                    {user?.name ?? "User"}
                  </span>
                  <span className="truncate font-mono text-[10px] text-sidebar-foreground/60">
                    {user?.email}
                  </span>
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
