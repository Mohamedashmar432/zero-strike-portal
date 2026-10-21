"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { CopyCommand } from "@/components/common/copy-command";
import { EmptyState } from "@/components/common/empty-state";
import { IntegrationsTable } from "@/components/settings/integrations/integrations-table";
import { useConnectedAppIntegrations } from "@/components/settings/integrations/use-connected-app-integrations";
import { useMcpTokenIntegrations } from "@/components/settings/integrations/use-mcp-token-integrations";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MCP_EXPIRY_CHOICES, mcpServerOrigin } from "@/lib/api/mcp-tokens";
import { userMcpUrl } from "@/lib/api/oauth";
import { useAuth } from "@/providers/auth-provider";

function Section({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold">{title}</h3>
        <p className="max-w-2xl text-sm text-muted-foreground">{description}</p>
      </div>
      {children}
    </section>
  );
}

export default function McpIntegrationsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const apps = useConnectedAppIntegrations();
  const tokens = useMcpTokenIntegrations(isAdmin);
  const [label, setLabel] = useState("");
  const [days, setDays] = useState<number>(30);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!label.trim()) return;
    tokens.issue({ label, days }, { onSuccess: () => setLabel("") });
  };

  return (
    <div className="space-y-8">
      <Section
        title="Connected apps"
        description="AI clients you have allowed to read your projects. They see only what you can see, read-only, and you can cut them off here at any time."
      >
        <div className="max-w-2xl space-y-1.5">
          <p className="text-xs text-muted-foreground">
            In Claude, ChatGPT or any MCP client, add a remote connector with this URL, then sign in and approve when
            asked.
          </p>
          <CopyCommand>{userMcpUrl(mcpServerOrigin())}</CopyCommand>
        </div>
        <IntegrationsTable
          rows={apps.rows}
          isLoading={apps.isLoading}
          isError={apps.isError}
          emptyState={<EmptyState title="No connected apps." />}
        />
      </Section>

      {isAdmin && (
        <Section
          title="Admin access tokens"
          description="Personal tokens that let an AI agent (Claude Code, Claude Desktop) read this portal's logs, queues and audit trail. Read-only; every call is audited; access ends the moment your admin role does."
        >
          <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
            <div className="space-y-2">
              <Label htmlFor="mcp-label">Label</Label>
              <Input
                id="mcp-label"
                value={label}
                maxLength={80}
                placeholder="e.g. my laptop"
                onChange={(e) => setLabel(e.target.value)}
                className="w-64"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="mcp-expiry">Expires in</Label>
              <select
                id="mcp-expiry"
                value={days}
                onChange={(e) => setDays(Number(e.target.value))}
                className="h-9 rounded-md border border-input bg-background px-3 text-sm"
              >
                {MCP_EXPIRY_CHOICES.map((d) => (
                  <option key={d} value={d}>
                    {d} days
                  </option>
                ))}
              </select>
            </div>
            <Button type="submit" disabled={!label.trim() || tokens.isIssuing}>
              {tokens.isIssuing ? "Issuing…" : "Issue token"}
            </Button>
          </form>
          <IntegrationsTable
            rows={tokens.rows}
            isLoading={tokens.isLoading}
            isError={tokens.isError}
            emptyState={<EmptyState title="No MCP tokens issued." />}
          />
        </Section>
      )}

      {apps.dialogs}
      {tokens.dialogs}
    </div>
  );
}
