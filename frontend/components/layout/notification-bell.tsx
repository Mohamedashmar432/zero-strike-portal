"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, CheckCheck } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { listNotifications, markNotificationsRead } from "@/lib/api/notifications";
import { queryKeys } from "@/lib/api/query-keys";
import { cn } from "@/lib/utils";

// Notifications arrive from background work (scans, audits, fix jobs), so the inbox is
// polled rather than pushed. 60s is slow enough to be invisible in request volume and fast
// enough that a finished scan shows up before someone goes looking for it.
const POLL_MS = 60_000;

function relativeTime(iso: string): string {
  // The API tags these UTC (core.timeutils.as_utc). Belt-and-braces: if an offset is ever
  // missing, `new Date()` would read the string as LOCAL time and every notification would
  // appear off by the viewer's UTC offset — which is exactly the bug this guards against.
  const hasOffset = /(Z|[+-]\d{2}:?\d{2})$/.test(iso);
  const seconds = Math.max(0, (Date.now() - new Date(hasOffset ? iso : iso + "Z").getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

// Design-system tokens only. There is no `status-warning` in the palette — the severity
// ramp is what carries "this needs attention", so warning borrows severity-medium.
const SEVERITY_DOT: Record<string, string> = {
  error: "bg-severity-critical",
  warning: "bg-severity-medium",
  success: "bg-status-success",
  info: "bg-signal",
};

export function NotificationBell() {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: queryKeys.notifications.list(),
    queryFn: () => listNotifications(20),
    refetchInterval: POLL_MS,
  });

  const markRead = useMutation({
    mutationFn: (id?: string) => markNotificationsRead(id),
    onSuccess: (updated) => queryClient.setQueryData(queryKeys.notifications.list(), updated),
  });

  const items = data?.items ?? [];
  const unread = data?.unread_count ?? 0;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={unread ? `Notifications (${unread} unread)` : "Notifications"}
            className="relative text-sidebar-foreground/55 hover:bg-sidebar-accent hover:text-sidebar-foreground"
          >
            <Bell className="size-4" />
            {/* Only rendered when something is actually unread — the previous version showed
                this dot unconditionally, which made it meaningless. */}
            {unread > 0 && (
              <span className="absolute right-0.5 top-0.5 size-1.5 rounded-full bg-signal" />
            )}
          </Button>
        }
      />
      <DropdownMenuContent align="start" side="right" className="w-80 p-0">
        <div className="flex items-center justify-between border-b border-border/60 px-3 py-2">
          <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            Notifications{unread > 0 ? ` · ${unread} unread` : ""}
          </span>
          {unread > 0 && (
            <button
              type="button"
              onClick={() => markRead.mutate(undefined)}
              className="flex items-center gap-1 font-mono text-[11px] text-muted-foreground hover:text-foreground"
            >
              <CheckCheck className="size-3" /> Mark all read
            </button>
          )}
        </div>

        {items.length === 0 ? (
          <p className="px-3 py-6 text-center text-sm text-muted-foreground">Nothing yet.</p>
        ) : (
          <div className="max-h-96 overflow-y-auto">
            {items.map((n) => {
              const body = (
                <>
                  <span className="flex items-start gap-2">
                    <span
                      className={cn(
                        "mt-1.5 size-1.5 shrink-0 rounded-full",
                        n.read_at ? "bg-transparent" : SEVERITY_DOT[n.severity] ?? "bg-signal"
                      )}
                    />
                    <span className="min-w-0 flex-1">
                      <span
                        className={cn(
                          "block truncate text-[13px]",
                          n.read_at ? "text-muted-foreground" : "font-medium text-foreground"
                        )}
                      >
                        {n.title}
                      </span>
                      {n.body && (
                        <span className="mt-0.5 block text-[11px] text-muted-foreground">
                          {n.body}
                        </span>
                      )}
                      <span className="mt-0.5 block font-mono text-[10px] text-muted-foreground">
                        {relativeTime(n.created_at)}
                      </span>
                    </span>
                  </span>
                </>
              );
              const className =
                "block w-full px-3 py-2.5 text-left transition-colors hover:bg-accent";
              // Opening a notification marks it read — the same gesture, not a second one.
              return n.link ? (
                <Link
                  key={n.id}
                  href={n.link}
                  className={className}
                  onClick={() => !n.read_at && markRead.mutate(n.id)}
                >
                  {body}
                </Link>
              ) : (
                <button
                  key={n.id}
                  type="button"
                  className={className}
                  onClick={() => !n.read_at && markRead.mutate(n.id)}
                >
                  {body}
                </button>
              );
            })}
          </div>
        )}

        <div className="border-t border-border/60 px-3 py-2">
          <Link
            href="/settings/notifications"
            className="font-mono text-[11px] text-muted-foreground hover:text-foreground"
          >
            Notification settings
          </Link>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
