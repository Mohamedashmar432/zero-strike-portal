"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "@/lib/api/client";
import {
  getGlobalAlerts,
  getProjectAlerts,
  testGlobalAlerts,
  testProjectAlerts,
  updateGlobalAlerts,
  updateProjectAlerts,
  type AlertTrigger,
} from "@/lib/api/alerts";
import { queryKeys } from "@/lib/api/query-keys";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";

const TRIGGERS: { key: AlertTrigger; label: string; hint: string }[] = [
  { key: "critical", label: "Critical findings", hint: "A scan finishes with one or more critical findings." },
  { key: "high", label: "High findings", hint: "A scan finishes with one or more high-severity findings." },
  { key: "vulnerable_package", label: "Vulnerable packages", hint: "A scan finds a dependency with a known vulnerability." },
  { key: "scan_failed", label: "Scan failed", hint: "A scan could not complete." },
];

const MAX_EMAILS = 3;

const err = (fallback: string) => (e: unknown) => toast.error(e instanceof ApiError ? e.message : fallback);

/** Webhook URL input. The stored URL is a secret and never comes back, so this shows the host and
 * only sends a URL when the user types a new one. */
function WebhookField({
  host,
  value,
  onChange,
  disabled,
}: {
  host: string | null;
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor="alert-webhook">Teams webhook URL</Label>
      <Input
        id="alert-webhook"
        type="url"
        autoComplete="off"
        placeholder={host ? `Saved (${host}) — paste a new URL to replace it` : "https://…webhook.office.com/…"}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
      <p className="text-xs text-muted-foreground">
        In Teams, open the channel → Workflows → “Post to a channel when a webhook request is received”, and paste
        its URL. It is stored encrypted and cannot be read back.
      </p>
      {host?.endsWith("webhook.office.com") && (
        <p className="text-xs text-severity-medium">
          This is a legacy Office 365 connector URL. Microsoft is retiring these: they can answer “OK” and still
          deliver nothing. If test alerts do not arrive, replace it with a Workflows webhook.
        </p>
      )}
    </div>
  );
}

export function ProjectAlertsCard({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const key = queryKeys.alerts.project(projectId);
  const alerts = useQuery({ queryKey: key, queryFn: () => getProjectAlerts(projectId) });
  const [url, setUrl] = useState("");
  const [draft, setDraft] = useState("");

  const save = useMutation({
    mutationFn: (body: Parameters<typeof updateProjectAlerts>[1]) => updateProjectAlerts(projectId, body),
    onSuccess: (data) => {
      queryClient.setQueryData(key, data);
      setUrl("");
      toast.success("Alert settings saved");
    },
    onError: err("Failed to save alert settings"),
  });
  const test = useMutation({
    mutationFn: () => testProjectAlerts(projectId),
    onSuccess: () => toast.success("Test alert sent — check the Teams channel"),
    onError: err("Test alert failed"),
  });

  const a = alerts.data;
  const emails = a?.emails ?? [];
  const draftEmail = draft.trim();
  const draftOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(draftEmail);
  // Adding or removing an address saves at once: there is no separate "save emails" step to forget.
  const saveEmails = (next: string[]) => save.mutate({ emails: next });
  function addEmail() {
    if (!draftOk || emails.length >= MAX_EMAILS) return;
    if (emails.some((e) => e.toLowerCase() === draftEmail.toLowerCase())) return setDraft("");
    saveEmails([...emails, draftEmail]);
    setDraft("");
  }
  const urlOk = !url.trim() || url.trim().startsWith("https://");

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-normal text-muted-foreground">Alerts &amp; webhooks</CardTitle>
        <p className="text-sm text-muted-foreground">
          Send security alerts for this project to a Teams channel and up to three mailboxes. Only project owners
          and admins can change this.
        </p>
      </CardHeader>
      <CardContent className="space-y-6">
        {!a ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <>
            <div className="space-y-3">
              <WebhookField host={a.webhook_host} value={url} onChange={setUrl} disabled={save.isPending} />
              <div className="flex items-center gap-3">
                <Switch
                  checked={a.webhook_enabled}
                  disabled={save.isPending || (!a.webhook_configured && !url.trim())}
                  onCheckedChange={(webhook_enabled) =>
                    save.mutate({ webhook_enabled, ...(url.trim() ? { webhook_url: url.trim() } : {}) })
                  }
                  aria-label="Send alerts to the webhook"
                />
                <span className="text-sm">Webhook alerts {a.webhook_enabled ? "on" : "off"}</span>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  disabled={save.isPending || !url.trim() || !urlOk}
                  onClick={() => save.mutate({ webhook_url: url.trim() })}
                >
                  Save webhook
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={test.isPending || !a.webhook_configured}
                  onClick={() => test.mutate()}
                >
                  {test.isPending ? "Sending…" : "Send test alert"}
                </Button>
                {a.webhook_configured && (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={save.isPending}
                    onClick={() => save.mutate({ webhook_url: "", webhook_enabled: false })}
                  >
                    Remove webhook
                  </Button>
                )}
              </div>
            </div>

            <div className="space-y-3">
              <Label htmlFor="alert-email-input">Alert emails (up to {MAX_EMAILS})</Label>
              <div className="flex gap-2">
                <Input
                  id="alert-email-input"
                  type="email"
                  placeholder="name@company.com"
                  value={draft}
                  disabled={save.isPending || emails.length >= MAX_EMAILS}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addEmail();
                    }
                  }}
                />
                <Button
                  type="button"
                  size="icon"
                  variant="outline"
                  aria-label="Add email"
                  disabled={save.isPending || !draftOk || emails.length >= MAX_EMAILS}
                  onClick={addEmail}
                >
                  <Plus className="size-4" />
                </Button>
              </div>
              {emails.length > 0 && (
                <ul className="flex flex-wrap gap-2">
                  {emails.map((e) => (
                    <li
                      key={e}
                      className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-sm"
                    >
                      {e}
                      <button
                        type="button"
                        aria-label={`Remove ${e}`}
                        disabled={save.isPending}
                        className="text-muted-foreground hover:text-foreground"
                        onClick={() => saveEmails(emails.filter((x) => x !== e))}
                      >
                        <X className="size-3.5" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <div className="flex items-center gap-3">
                <Switch
                  checked={a.email_enabled}
                  disabled={save.isPending || (emails.length === 0 && !a.email_enabled)}
                  onCheckedChange={(email_enabled) => save.mutate({ email_enabled })}
                  aria-label="Send alerts by email"
                />
                <span className="text-sm">Email alerts {a.email_enabled ? "on" : "off"}</span>
              </div>
              <p className="text-xs text-muted-foreground">
                Email is only delivered when the portal&apos;s SMTP server is configured.
              </p>
            </div>

            <div className="space-y-3">
              <Label>Send an alert when</Label>
              {TRIGGERS.map((t) => (
                <div key={t.key} className="flex items-center justify-between gap-4">
                  <div>
                    <p className="text-sm">{t.label}</p>
                    <p className="text-xs text-muted-foreground">{t.hint}</p>
                  </div>
                  <Switch
                    checked={a.triggers.includes(t.key)}
                    disabled={save.isPending}
                    onCheckedChange={(on) =>
                      save.mutate({
                        triggers: on ? [...a.triggers, t.key] : a.triggers.filter((x) => x !== t.key),
                      })
                    }
                    aria-label={t.label}
                  />
                </div>
              ))}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export function GlobalAlertsCard() {
  const queryClient = useQueryClient();
  const key = queryKeys.alerts.global();
  const alerts = useQuery({ queryKey: key, queryFn: getGlobalAlerts });
  const [url, setUrl] = useState("");

  const save = useMutation({
    mutationFn: updateGlobalAlerts,
    onSuccess: (data) => {
      queryClient.setQueryData(key, data);
      setUrl("");
      toast.success("Webhook settings saved");
    },
    onError: err("Failed to save webhook settings"),
  });
  const test = useMutation({
    mutationFn: testGlobalAlerts,
    onSuccess: () => toast.success("Test alert sent — check the Teams channel"),
    onError: err("Test alert failed"),
  });

  const a = alerts.data;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-normal text-muted-foreground">Portal webhook (admin events)</CardTitle>
        <p className="text-sm text-muted-foreground">
          Posts portal-wide admin events — signup requests, scanner health, allowance requests — to a Teams
          channel. Project security alerts are configured per project, under Project Settings.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {!a ? (
          <Skeleton className="h-20 w-full" />
        ) : (
          <>
            <WebhookField host={a.webhook_host} value={url} onChange={setUrl} disabled={save.isPending} />
            <div className="flex items-center gap-3">
              <Switch
                checked={a.webhook_enabled}
                disabled={save.isPending || (!a.webhook_configured && !url.trim())}
                onCheckedChange={(webhook_enabled) =>
                  save.mutate({ webhook_enabled, ...(url.trim() ? { webhook_url: url.trim() } : {}) })
                }
                aria-label="Send admin events to the webhook"
              />
              <span className="text-sm">Webhook {a.webhook_enabled ? "on" : "off"}</span>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                disabled={save.isPending || !url.trim() || !url.trim().startsWith("https://")}
                onClick={() => save.mutate({ webhook_url: url.trim() })}
              >
                Save webhook
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={test.isPending || !a.webhook_configured}
                onClick={() => test.mutate()}
              >
                {test.isPending ? "Sending…" : "Send test alert"}
              </Button>
              {a.webhook_configured && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={save.isPending}
                  onClick={() => save.mutate({ webhook_url: "", webhook_enabled: false })}
                >
                  Remove webhook
                </Button>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
