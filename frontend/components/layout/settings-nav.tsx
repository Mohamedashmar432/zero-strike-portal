"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { settingsLinks } from "./nav-links";

export function SettingsNav() {
  const pathname = usePathname();

  return (
    // Same rack-row language as the main rail: flush lime marker, mono label,
    // square corners — so settings doesn't feel like a different application.
    <nav className="space-y-0.5">
      {settingsLinks.map((link) => {
        const isActive = pathname?.startsWith(link.href) ?? false;
        return (
          <Link
            key={link.href}
            href={link.href}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "relative flex items-center gap-2.5 rounded-sm px-3 py-2 font-mono text-[13px] tracking-[-0.01em] text-muted-foreground transition-colors duration-150 hover:bg-accent hover:text-accent-foreground",
              isActive && "bg-accent font-semibold text-accent-foreground"
            )}
          >
            {isActive && <span className="absolute inset-y-1 left-0 w-[3px] bg-signal" />}
            <link.icon
              className={cn("size-4 shrink-0", isActive ? "text-signal" : "text-muted-foreground")}
            />
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
