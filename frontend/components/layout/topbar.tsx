"use client";

import { Bell, Search, Settings } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useState } from "react";
import { toast } from "sonner";
import { MobileNav } from "./mobile-nav";
import { ThemeToggle } from "./theme-toggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function Topbar() {
  const router = useRouter();
  const [search, setSearch] = useState("");

  function handleSearchSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (search.trim()) router.push(`/projects?q=${encodeURIComponent(search.trim())}`);
  }

  return (
    <header className="flex h-16 items-center gap-4 border-b border-border bg-card px-6">
      <MobileNav />
      <form onSubmit={handleSearchSubmit} className="hidden max-w-md flex-1 md:block">
        <div className="relative">
          <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search projects or vulnerabilities…"
            className="rounded-full pl-9"
          />
        </div>
      </form>
      <div className="ml-auto flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          aria-label="Notifications"
          className="relative"
          onClick={() => toast.info("No new notifications")}
        >
          <Bell />
          <span className="absolute top-1.5 right-1.5 size-1.5 rounded-full bg-destructive" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Settings"
          nativeButton={false}
          render={<Link href="/settings/profile" />}
        >
          <Settings />
        </Button>
        <ThemeToggle />
      </div>
    </header>
  );
}
