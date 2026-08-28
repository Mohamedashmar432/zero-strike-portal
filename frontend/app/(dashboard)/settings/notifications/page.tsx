"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Info, Mail } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError } from "@/lib/api/client";
import {
  getNotificationPreferences,
  updateNotificationPreferences,
  type NotificationPreferences,
} from "@/lib/api/notifications";
import { queryKeys } from "@/lib/api/query-keys";

export default function NotificationSettingsPage() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.notifications.preferences(),
    queryFn: getNotificationPreferences,
  });

  const [form, setForm] = useState<NotificationPreferences | null>(null);
  const [syncedFrom, setSyncedFrom] = useState<NotificationPreferences | null>(null);
  if (data && data !== syncedFrom) {
    setSyncedFrom(data);
    setForm(data);
  }

  const save = useMutation({
    mutationFn: (body: NotificationPreferences) =>
      updateNotificationPreferences({ in_app: body.in_app, email: body.email }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.notifications.preferences(), updated);
      toast.success("Notification preferences saved");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to save"),
  });

  if (isLoading || !form) {
    return <p className="text-sm text-muted-foreground">Loading preferences…</p>;
  }

  function toggle(channel: "in_app" | "email", key: string) {
    setForm((f) =>
      f
        ? {
            ...f,
            [channel]: f[channel].includes(key)
              ? f[channel].filter((k) => k !== key)
              : [...f[channel], key],
          }
        : f
    );
  }

  // No filtering here: the API already returns only the events this user can receive, so the
  // grid and the payload we save back cannot disagree.

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Notifications</h2>
        <p className="text-sm text-muted-foreground">
          Choose when the portal notifies you. These are your preferences — they don&apos;t affect
          anyone else on your projects.
        </p>
      </div>

      {!form.email_delivery_configured && (
        <Alert>
          <Mail />
          <AlertTitle>Email delivery isn&apos;t configured</AlertTitle>
          <AlertDescription>
            Email preferences save, but nothing is sent until an administrator configures an SMTP
            host on the server. In-app notifications work regardless.
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Bell className="size-4" /> Events
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/60 text-left">
                  <th className="py-2 pr-4 font-medium">Event</th>
                  <th className="w-20 py-2 text-center font-medium">In app</th>
                  <th className="w-20 py-2 text-center font-medium">Email</th>
                </tr>
              </thead>
              <tbody>
                {form.events.map((event) => (
                  <tr key={event.key} className="border-b border-border/30 align-top">
                    <td className="py-3 pr-4">
                      <span className="flex items-center gap-2 font-medium">
                        {event.label}
                        {event.audience === "admin" && (
                          <Badge variant="outline" className="font-mono text-[10px]">
                            Admins
                          </Badge>
                        )}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {event.description}
                      </span>
                    </td>
                    <td className="py-3 text-center">
                      <input
                        type="checkbox"
                        className="size-4"
                        aria-label={`${event.label} in app`}
                        checked={form.in_app.includes(event.key)}
                        onChange={() => toggle("in_app", event.key)}
                      />
                    </td>
                    <td className="py-3 text-center">
                      <input
                        type="checkbox"
                        className="size-4"
                        aria-label={`${event.label} by email`}
                        checked={form.email.includes(event.key)}
                        onChange={() => toggle("email", event.key)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="flex items-start gap-2 text-xs text-muted-foreground">
            <Info className="mt-0.5 size-3.5 shrink-0" />
            <span>
              You only receive project events for projects you&apos;re a member of. In-app
              notifications are kept for 90 days.
            </span>
          </p>

          <Button onClick={() => save.mutate(form)} disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save preferences"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
