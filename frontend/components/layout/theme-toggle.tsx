"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";

function subscribe() {
  return () => {};
}

// next-themes only knows the real theme on the client (it reads
// localStorage/media queries), so the server render and the first client
// render must intentionally match ("not mounted yet") to avoid a hydration
// mismatch — useSyncExternalStore flips this to true once hydration
// completes, without a setState-in-effect render cascade.
function useMounted() {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false
  );
}

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useMounted();

  if (!mounted) {
    return (
      <Button
        variant="ghost"
        size="icon-xs"
        disabled
        aria-label="Toggle theme"
        className="text-sidebar-foreground/55"
      >
        <Sun />
      </Button>
    );
  }

  const isDark = resolvedTheme === "dark";

  return (
    <Button
      variant="ghost"
      size="icon-xs"
      aria-label="Toggle theme"
      title={isDark ? "Switch to light" : "Switch to dark"}
      className="text-sidebar-foreground/55 hover:bg-sidebar-accent hover:text-sidebar-foreground"
      onClick={() => setTheme(isDark ? "light" : "dark")}
    >
      {isDark ? <Sun /> : <Moon />}
    </Button>
  );
}
