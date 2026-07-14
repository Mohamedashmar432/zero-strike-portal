"use client";

import { MobileNav } from "./mobile-nav";
import { ThemeToggle } from "./theme-toggle";

export function Topbar() {
  return (
    <header className="flex h-16 items-center justify-between border-b border-border bg-card px-6">
      <MobileNav />
      <ThemeToggle />
    </header>
  );
}
