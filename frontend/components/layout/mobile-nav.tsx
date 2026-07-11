"use client";

import { Menu } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { useAuth } from "@/providers/auth-provider";
import { adminLinks, mainLinks, settingsLinks } from "./nav-links";

export function MobileNav() {
  const pathname = usePathname();
  const { user } = useAuth();

  return (
    <Sheet>
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
            <span className="font-mono text-sm font-semibold tracking-tight">
              zero<span className="text-brand">strike</span>
            </span>
          </SheetTitle>
        </SheetHeader>
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
      </SheetContent>
    </Sheet>
  );
}
