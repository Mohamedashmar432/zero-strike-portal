"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { settingsLinks } from "./nav-links";

export function SettingsNav() {
  const pathname = usePathname();

  return (
    <nav className="space-y-1">
      {settingsLinks.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          className={cn(
            "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground",
            pathname?.startsWith(link.href) && "bg-accent font-medium text-accent-foreground"
          )}
        >
          <link.icon className="size-[18px]" />
          {link.label}
        </Link>
      ))}
    </nav>
  );
}
