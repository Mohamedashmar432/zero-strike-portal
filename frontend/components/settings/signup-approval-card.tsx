"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { listUsers } from "@/lib/api/users";
import {
  getWorkspaceSettings,
  listEmailTemplates,
  sendTestEmail,
  updateEmailTemplate,
  updateWorkspaceSettings,
  type EmailTemplate,
} from "@/lib/api/workspace-settings";

const errorMessage = (err: unknown, fallback: string) =>
  err instanceof ApiError ? err.message : fallback;

function TemplateEditor({ template }: { template: EmailTemplate }) {
  const queryClient = useQueryClient();
  const [subject, setSubject] = useState(template.subject ?? template.default_subject);
  const [body, setBody] = useState(template.body ?? template.default_body);
  const customised = template.subject !== null || template.body !== null;

  const save = useMutation({
    // Sending the default text back is stored as "no override", so a later change to the
    // built-in wording still reaches templates nobody customised.
    mutationFn: (reset: boolean) =>
      updateEmailTemplate(template.key, {
        subject: reset || subject === template.default_subject ? "" : subject,
        body: reset || body === template.default_body ? "" : body,
      }),
    onSuccess: (updated, reset) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.settings.emailTemplates() });
      if (reset) {
        setSubject(updated.default_subject);
        setBody(updated.default_body);
      }
      toast.success(reset ? "Reset to the default wording" : "Template saved");
    },
    onError: (err) => toast.error(errorMessage(err, "Failed to save template")),
  });

  const test = useMutation({
    mutationFn: () => sendTestEmail(template.key),
    onSuccess: (r) => toast.success(r.message),
    onError: (err) => toast.error(errorMessage(err, "Failed to send test email")),
  });

  return (
    <div className="space-y-3 rounded-md border border-border/60 p-4">
      <div>
        <p className="text-sm font-medium">{template.label}</p>
        <p className="text-xs text-muted-foreground">{template.description}</p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={`${template.key}-subject`}>Subject</Label>
        <Input
          id={`${template.key}-subject`}
          value={subject}
          maxLength={200}
          onChange={(e) => setSubject(e.target.value)}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={`${template.key}-body`}>Message</Label>
        <Textarea
          id={`${template.key}-body`}
          rows={7}
          value={body}
          maxLength={5000}
          onChange={(e) => setBody(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          Available placeholders:{" "}
          {template.placeholders.map((p) => (
            <code key={p} className="mr-1.5 font-mono">{`{${p}}`}</code>
          ))}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={save.isPending} onClick={() => save.mutate(false)}>
          {save.isPending ? "Saving…" : "Save template"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={save.isPending || !customised}
          onClick={() => save.mutate(true)}
        >
          Reset to default
        </Button>
        <Button size="sm" variant="outline" disabled={test.isPending} onClick={() => test.mutate()}>
          {test.isPending ? "Sending…" : "Send test to me"}
        </Button>
      </div>
    </div>
  );
}

/** Admin-only: signup approval switch, who reviews requests, and the emails they trigger. */
export function SignupApprovalCard() {
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: queryKeys.settings.workspace(),
    queryFn: getWorkspaceSettings,
  });
  const admins = useQuery({
    queryKey: ["admin", "users", "admins"],
    // The user list has no role filter; portals have a handful of admins among few users.
    queryFn: () => listUsers(1, 100),
    select: (page) => page.items.filter((u) => u.role === "admin" && u.is_active),
  });
  const templates = useQuery({
    queryKey: queryKeys.settings.emailTemplates(),
    queryFn: listEmailTemplates,
  });

  const update = useMutation({
    mutationFn: updateWorkspaceSettings,
    onSuccess: (ws) => {
      queryClient.setQueryData(queryKeys.settings.workspace(), ws);
      toast.success("Signup settings saved");
    },
    onError: (err) => toast.error(errorMessage(err, "Failed to save")),
  });

  if (!settings.data) return null;
  const chosen = settings.data.signup_notify_admin_ids;
  const toggleAdmin = (id: string) =>
    update.mutate({
      signup_notify_admin_ids: chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id],
    });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <UserCheck className="size-4" /> Signup approval
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <Label htmlFor="signup-approval">Require admin approval for new accounts</Label>
            <p className="text-xs text-muted-foreground">
              New registrations cannot sign in until an admin approves them. Existing users are
              not affected. Ignored while the portal has no admin, so the first account can be
              created.
            </p>
          </div>
          <Switch
            id="signup-approval"
            checked={settings.data.signup_requires_approval}
            disabled={update.isPending}
            onCheckedChange={(v) => update.mutate({ signup_requires_approval: v })}
          />
        </div>

        <div className="space-y-2">
          <p className="text-sm font-medium">Who is emailed about new requests</p>
          <p className="text-xs text-muted-foreground">
            {chosen.length === 0
              ? "Nobody is selected, so every admin is emailed. Select admins to limit it."
              : "Only the selected admins are emailed. Others can still review requests on the Users page."}
          </p>
          {admins.data?.map((a) => (
            <label key={a.id} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4"
                checked={chosen.includes(a.id)}
                disabled={update.isPending}
                onChange={() => toggleAdmin(a.id)}
              />
              <span>{a.name}</span>
              <span className="font-mono text-xs text-muted-foreground">{a.email}</span>
            </label>
          ))}
        </div>

        <div className="space-y-3">
          <p className="text-sm font-medium">Email wording</p>
          {templates.data?.map((t) => (
            <TemplateEditor key={`${t.key}:${t.subject}:${t.body}`} template={t} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
