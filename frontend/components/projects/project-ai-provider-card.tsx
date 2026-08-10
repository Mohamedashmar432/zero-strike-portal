"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2, KeyRound } from "lucide-react";

import { ApiError } from "@/lib/api/client";
import {
  activateProjectAiProvider,
  createProjectAiProvider,
  deleteProjectAiProvider,
  getAiSettings,
  listProjectAiProviders,
  testProjectAiProvider,
  updateProjectAiProvider,
  type AiProvider,
  type AiProviderConfig,
} from "@/lib/api/ai";
import { queryKeys } from "@/lib/api/query-keys";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";

/** Same list the backend accepts. Self-hosted ones need no key. */
const PROVIDERS: { value: AiProvider; label: string; keyless?: boolean }[] = [
  { value: "anthropic", label: "Anthropic" },
  { value: "openai", label: "OpenAI" },
  { value: "gemini", label: "Google Gemini" },
  { value: "groq", label: "Groq" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "nvidia_nim", label: "NVIDIA NIM" },
  { value: "kimi", label: "Kimi (Moonshot)" },
  { value: "commandcode", label: "CommandCode" },
  { value: "lmstudio", label: "LM Studio (self-hosted)", keyless: true },
  { value: "custom", label: "Custom OpenAI-compatible", keyless: true },
];

const BLANK = {
  name: "",
  provider: "anthropic" as AiProvider,
  model_name: "",
  api_key: "",
  base_url: "",
};

export function ProjectAiProviderCard({
  projectId,
  canManage,
}: {
  projectId: string;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: queryKeys.ai.settings(), queryFn: getAiSettings });
  const providers = useQuery({
    queryKey: queryKeys.projects.aiProviders(projectId),
    // Only meaningful once BYOK is on; skipping the call keeps a normal workspace's settings
    // page down to the requests it actually needs.
    enabled: settings.data?.project_byok_enabled === true,
    queryFn: () => listProjectAiProviders(projectId),
  });

  const [form, setForm] = useState(BLANK);
  const [editingId, setEditingId] = useState<string | null>(null);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.projects.aiProviders(projectId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.projects.aiUsage(projectId) });
  };
  const fail = (fallback: string) => (err: unknown) =>
    toast.error(err instanceof ApiError ? err.message : fallback);

  const save = useMutation({
    mutationFn: () => {
      const base = {
        name: form.name.trim() || `${form.provider} key`,
        provider: form.provider,
        model_name: form.model_name.trim(),
        base_url: form.base_url.trim() || undefined,
      };
      if (editingId) {
        // api_key omitted (not empty-string) means "keep the stored key" — see the backend's
        // omitted-vs-clear semantics.
        return updateProjectAiProvider(projectId, editingId, {
          ...base,
          api_key: form.api_key.trim() || undefined,
        });
      }
      return createProjectAiProvider(projectId, { ...base, api_key: form.api_key.trim() });
    },
    onSuccess: () => {
      invalidate();
      setForm(BLANK);
      setEditingId(null);
      toast.success(editingId ? "Provider updated" : "Provider added");
    },
    onError: fail("Failed to save the provider"),
  });

  const activate = useMutation({
    mutationFn: (id: string) => activateProjectAiProvider(projectId, id),
    onSuccess: () => {
      invalidate();
      toast.success("Provider activated");
    },
    onError: fail("Failed to activate the provider"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteProjectAiProvider(projectId, id),
    onSuccess: () => {
      invalidate();
      toast.success("Provider removed");
    },
    onError: fail("Failed to remove the provider"),
  });

  const test = useMutation({
    mutationFn: (id: string) => testProjectAiProvider(projectId, id),
    onSuccess: () => toast.success("Connection successful"),
    onError: fail("Connection failed"),
  });

  // BYOK off = this project runs on the portal-wide provider and there is nothing to configure.
  if (!settings.data?.project_byok_enabled) return null;

  const keyless = PROVIDERS.find((p) => p.value === form.provider)?.keyless === true;
  const rows = providers.data ?? [];
  const startEdit = (config: AiProviderConfig) => {
    setEditingId(config.id);
    setForm({
      name: config.name,
      provider: config.provider,
      model_name: config.model_name ?? "",
      api_key: "",
      base_url: config.base_url ?? "",
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-normal text-muted-foreground">
          AI Provider (BYOK)
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          This project runs AI analysis, auto-fix and compliance on its own key. Its usage is
          billed to you and never falls back to the portal&apos;s provider — without a key here,
          AI features are unavailable for this project.
        </p>
      </CardHeader>
      <CardContent className="space-y-6">
        {providers.isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No provider configured yet.</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {rows.map((config) => (
              <li key={config.id} className="flex flex-wrap items-center gap-3 p-3">
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 text-sm font-medium">
                    {config.name}
                    {config.is_active && (
                      <Badge variant="secondary" className="gap-1">
                        <CheckCircle2 className="size-3" />
                        Active
                      </Badge>
                    )}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    {config.provider}
                    {config.model_name ? ` · ${config.model_name}` : ""} ·{" "}
                    {config.has_api_key ? (
                      <span className="inline-flex items-center gap-1">
                        <KeyRound className="size-3" />
                        •••• configured
                      </span>
                    ) : (
                      "no key"
                    )}
                  </p>
                </div>
                {canManage && (
                  <div className="flex flex-wrap gap-2">
                    {!config.is_active && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => activate.mutate(config.id)}
                        disabled={activate.isPending}
                      >
                        Activate
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => test.mutate(config.id)}
                      disabled={test.isPending}
                    >
                      {test.isPending ? "Testing…" : "Test connection"}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => startEdit(config)}>
                      Edit
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-destructive"
                      onClick={() => remove.mutate(config.id)}
                      disabled={remove.isPending}
                    >
                      Remove
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}

        {canManage && (
          <div className="space-y-4 border-t pt-4">
            <p className="text-sm font-medium">
              {editingId ? "Edit provider" : "Add a provider"}
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="byok-name">Label</Label>
                <Input
                  id="byok-name"
                  value={form.name}
                  placeholder="Team Anthropic key"
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="byok-provider">Provider</Label>
                <Select
                  value={form.provider}
                  onValueChange={(v) => v && setForm({ ...form, provider: v as AiProvider })}
                >
                  <SelectTrigger id="byok-provider">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PROVIDERS.map((p) => (
                      <SelectItem key={p.value} value={p.value}>
                        {p.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="byok-model">Model</Label>
                <Input
                  id="byok-model"
                  value={form.model_name}
                  placeholder="claude-sonnet-4-5"
                  onChange={(e) => setForm({ ...form, model_name: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="byok-key">API key</Label>
                <Input
                  id="byok-key"
                  type="password"
                  autoComplete="off"
                  value={form.api_key}
                  placeholder={
                    keyless
                      ? "Not required for this provider"
                      : editingId
                        ? "Leave blank to keep the stored key"
                        : "sk-…"
                  }
                  disabled={keyless}
                  onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                />
              </div>
              {(keyless || form.base_url) && (
                <div className="space-y-2 sm:col-span-2">
                  <Label htmlFor="byok-base-url">Base URL</Label>
                  <Input
                    id="byok-base-url"
                    value={form.base_url}
                    placeholder="http://localhost:1234/v1"
                    onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                  />
                </div>
              )}
            </div>
            <div className="flex gap-2">
              <Button
                onClick={() => save.mutate()}
                disabled={
                  save.isPending ||
                  !form.model_name.trim() ||
                  (!editingId && !keyless && !form.api_key.trim())
                }
              >
                {save.isPending ? "Saving…" : editingId ? "Save changes" : "Add provider"}
              </Button>
              {editingId && (
                <Button
                  variant="outline"
                  onClick={() => {
                    setEditingId(null);
                    setForm(BLANK);
                  }}
                >
                  Cancel
                </Button>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
