"use client";

import { Menu, Settings } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { RequireRole } from "@/components/auth/require-role";
import { ZeroStrikeLogo } from "@/components/brand/logo";
import { cn, getInitials } from "@/lib/utils";
import { useAuth } from "@/providers/auth-provider";
import { adminLinks, mainLinks } from "./nav-links";

// Same rack-row language as the desktop rail: flush lime marker, mono label,
// square corners. Three near-identical link blocks previously repeated this.
function MobileNavItem({
  href,
  label,
  icon: Icon,
  isActive,
}: {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  isActive: boolean;
}) {
  return (
    <Link
      href={href}
      aria-current={isActive ? "page" : undefined}
      className={cn(
        "relative flex items-center gap-3 rounded-sm px-3 py-2.5 font-mono text-[13px] tracking-[-0.01em] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
        isActive && "bg-accent font-semibold text-foreground"
      )}
    >
      {isActive && <span className="absolute inset-y-1 left-0 w-[3px] bg-signal" />}
      <Icon className={cn("size-4 shrink-0", isActive ? "text-signal" : "text-muted-foreground")} />
      {label}
    </Link>
  );
}

export function MobileNav() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);

  // Close the drawer once navigation actually completes (pathname changes), rather than
  // on link click — a click-handler close would race the route transition and could
  // flash-close before the new page paints. Adjusted during render (see the same pattern
  // in admin/users/page.tsx) instead of a useEffect, which would cost an extra render pass.
  const [prevPathname, setPrevPathname] = useState(pathname);
  if (pathname !== prevPathname) {
    setPrevPathname(pathname);
    setOpen(false);
  }

  async function handleLogout() {
    setOpen(false);
    await logout();
    router.push("/login");
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger
        render={
          <Button
            variant="outline"
            size="icon"
            className="border-border bg-card md:hidden"
            aria-label="Open navigation menu"
          >
            <Menu />
          </Button>
        }
      />
      <SheetContent side="left">
        <SheetHeader className="pb-2">
          <SheetTitle>
            <ZeroStrikeLogo size="sm" />
          </SheetTitle>
        </SheetHeader>
        <nav className="flex-1 space-y-0.5 px-2">
          {mainLinks.map((link) => (
            <MobileNavItem
              key={link.href}
              {...link}
              isActive={pathname?.startsWith(link.href) ?? false}
            />
          ))}
          <RequireRole role="admin">
            <div className="legend px-3 pb-1.5 pt-4 text-muted-foreground">Administration</div>
            {adminLinks.map((link) => (
              <MobileNavItem
                key={link.href}
                {...link}
                isActive={pathname?.startsWith(link.href) ?? false}
              />
            ))}
          </RequireRole>
          <div className="legend px-3 pb-1.5 pt-4 text-muted-foreground">Workspace</div>
          <MobileNavItem
            href="/settings/profile"
            label="Settings"
            icon={Settings}
            isActive={pathname?.startsWith("/settings") ?? false}
          />
        </nav>
        <div className="border-t border-border p-2">
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <button className="flex w-full cursor-pointer items-center gap-2.5 rounded-sm px-2 py-2 text-left transition-colors hover:bg-accent">
                  <Avatar size="sm" className="rounded-sm">
                    <AvatarFallback className="rounded-sm bg-signal/15 font-mono text-[11px] font-bold text-signal">
                      {getInitials(user?.name ?? user?.email ?? "?")}
                    </AvatarFallback>
                  </Avatar>
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="truncate font-mono text-[12px] font-semibold text-foreground">
                      {user?.name ?? "…"}
                    </span>
                    <span className="truncate font-mono text-[10px] text-muted-foreground">
                      {user?.email}
                    </span>
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
      </SheetContent>
    </Sheet>
  );
}
