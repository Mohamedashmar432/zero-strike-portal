"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const SECTIONS = [
  { href: "/settings/integrations", label: "Overview", exact: true },
  { href: "/settings/integrations/source-control", label: "Source control" },
  { href: "/settings/integrations/mcp", label: "AI agents (MCP)" },
];

export function IntegrationsSubNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Integration sections" className="flex flex-wrap gap-1 border-b border-hairline">
      {SECTIONS.map((s) => {
        const active = s.exact ? pathname === s.href : (pathname?.startsWith(s.href) ?? false);
        return (
          <Link
            key={s.href}
            href={s.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "-mb-px whitespace-nowrap border-b-2 px-3 py-2 font-mono text-[13px] tracking-[-0.01em] transition-colors",
              active
                ? "border-signal font-semibold text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {s.label}
          </Link>
        );
      })}
    </nav>
  );
}
