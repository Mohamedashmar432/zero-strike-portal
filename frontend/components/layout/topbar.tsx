"use client";

import { MobileNav } from "./mobile-nav";
import { ThemeToggle } from "./theme-toggle";

export function Topbar() {
  return (
    <header className="flex h-14 items-center justify-between border-b border-border px-4">
      <MobileNav />
      <ThemeToggle />
    </header>
  );
}
