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
import { cn, getInitials } from "@/lib/utils";
import { useAuth } from "@/providers/auth-provider";
import { adminLinks, mainLinks } from "./nav-links";

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
          <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open navigation menu">
            <Menu />
          </Button>
        }
      />
      <SheetContent side="left">
        <SheetHeader>
          <SheetTitle>
            <span className="text-sm font-bold tracking-tight">
              <span className="text-primary">Zero</span>Strike
            </span>
          </SheetTitle>
        </SheetHeader>
        <nav className="flex-1 space-y-1 px-2">
          {mainLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-foreground",
                pathname?.startsWith(link.href) && "bg-accent text-foreground"
              )}
            >
              <link.icon className="size-[18px]" />
              {link.label}
            </Link>
          ))}
          <RequireRole role="admin">
            <div className="px-3 pt-4 pb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Admin
            </div>
            {adminLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-foreground",
                  pathname?.startsWith(link.href) && "bg-accent text-foreground"
                )}
              >
                <link.icon className="size-[18px]" />
                {link.label}
              </Link>
            ))}
          </RequireRole>
          <Link
            href="/settings/profile"
            className={cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-foreground",
              pathname?.startsWith("/settings") && "bg-accent text-foreground"
            )}
          >
            <Settings className="size-[18px]" />
            Settings
          </Link>
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
      </SheetContent>
    </Sheet>
  );
}
