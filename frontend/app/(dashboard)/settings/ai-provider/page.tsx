"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { RequireRole } from "@/components/auth/require-role";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useHasRole } from "@/lib/hooks/use-has-role";
import {
  activateAiProvider,
  createAiProvider,
  deactivateAiProvider,
  deleteAiProvider,
  listAiProviders,
  testAiProviderConnection,
  updateAiProvider,
  type AiProvider,
  type AiProviderConfig,
  type CreateAiProviderInput,
  type TestAiProviderInput,
  type UpdateAiProviderInput,
} from "@/lib/api/ai";
import { ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { formatRelativeTime } from "@/lib/utils";
import { aiProviderFormSchema, type AiProviderFormValues } from "@/lib/validation/ai-provider.schema";

const PROVIDERS: { value: AiProvider; label: string }[] = [
  { value: "anthropic", label: "Anthropic" },
  { value: "openai", label: "OpenAI" },
  { value: "lmstudio", label: "LM Studio" },
  { value: "kimi", label: "Kimi" },
  { value: "nvidia_nim", label: "NVIDIA NIM" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "custom", label: "Custom" },
  { value: "commandcode", label: "Command Code AI" },
];

const PROVIDER_LABELS = Object.fromEntries(PROVIDERS.map((p) => [p.value, p.label])) as Record<
  AiProvider,
  string
>;

// Self-hosted providers need an endpoint; hosted ones ship a known default (mirrors the
// .refine in ai-provider.schema.ts).
const SELF_HOSTED_PROVIDERS: AiProvider[] = ["lmstudio", "custom"];

const tokenFormatter = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const costFormatter = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

type DialogTarget = { mode: "create" } | { mode: "edit"; provider: AiProviderConfig };

function AiProviderDialog({ target, onClose }: { target: DialogTarget | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const isEdit = target?.mode === "edit";

  const {
    register,
    handleSubmit,
    setValue,
    setError,
    clearErrors,
    reset,
    formState: { errors },
  } = useForm<AiProviderFormValues>({
    resolver: zodResolver(aiProviderFormSchema),
    defaultValues: { name: "", provider: "anthropic", model_name: "", base_url: "", api_key: "" },
    // Keeps the form synced to whichever row (or blank create) is being targeted -- same
    // idiom as the old single-settings form, keyed off `target` instead of query data.
    // api_key is always left blank: the raw/encrypted key is never returned by the backend.
    values: target
      ? target.mode === "edit"
        ? {
            name: target.provider.name,
            provider: target.provider.provider,
            model_name: target.provider.model_name ?? "",
            base_url: target.provider.base_url ?? "",
            api_key: "",
          }
        : { name: "", provider: "anthropic", model_name: "", base_url: "", api_key: "" }
      : undefined,
  });

  // Mirrors the RHF-registered `provider` field so the Select can be controlled without
  // react-hook-form's `watch()` (same pattern as the old single-settings form and
  // components/repos/credential-form.tsx). Synced from `target` during render rather than
  // in an effect -- see
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes.
  const [provider, setProvider] = useState<AiProvider>(
    target?.mode === "edit" ? target.provider.provider : "anthropic"
  );
  const [syncedFrom, setSyncedFrom] = useState(target);
  if (target !== syncedFrom) {
    setSyncedFrom(target);
    setProvider(target?.mode === "edit" ? target.provider.provider : "anthropic");
  }

  function buildTestInput(values: AiProviderFormValues): TestAiProviderInput {
    return {
      id: target?.mode === "edit" ? target.provider.id : undefined,
      provider: values.provider,
      model_name: values.model_name,
      api_key: values.api_key || undefined,
      base_url: values.base_url || undefined,
    };
  }

  const test = useMutation({
    mutationFn: (input: TestAiProviderInput) => testAiProviderConnection(input),
    onSuccess: () => toast.success("Connection successful"),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Connection test failed"),
  });

  const create = useMutation({
    mutationFn: (input: CreateAiProviderInput) => createAiProvider(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.ai.providers.all() });
      queryClient.invalidateQueries({ queryKey: queryKeys.ai.status() });
      toast.success("Provider added");
      reset();
      onClose();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to add provider"),
  });

  const update = useMutation({
    mutationFn: ({ id, input }: { id: string; input: UpdateAiProviderInput }) => updateAiProvider(id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.ai.providers.all() });
      queryClient.invalidateQueries({ queryKey: queryKeys.ai.status() });
      toast.success("Provider updated");
      reset();
      onClose();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to update provider"),
  });

  function onSubmit(values: AiProviderFormValues) {
    if (!isEdit && !values.api_key) {
      setError("api_key", { message: "An API key is required" });
      return;
    }
    clearErrors("api_key");
    if (target?.mode === "edit") {
      update.mutate({
        id: target.provider.id,
        input: {
          name: values.name,
          provider: values.provider,
          model_name: values.model_name,
          base_url: values.base_url || undefined,
          api_key: values.api_key || undefined,
        },
      });
    } else {
      create.mutate({
        name: values.name,
        provider: values.provider,
        model_name: values.model_name,
        base_url: values.base_url || undefined,
        api_key: values.api_key ?? "",
      });
    }
  }

  const isSaving = create.isPending || update.isPending;

  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <form onSubmit={handleSubmit(onSubmit)}>
          <DialogHeader>
            <DialogTitle>{isEdit ? "Edit provider" : "Add provider"}</DialogTitle>
            <DialogDescription>
              {isEdit
                ? "Update this provider's configuration. Leave the API key blank to keep the one already saved."
                : "Configure another AI provider for finding analysis. You can add several and switch which one is active."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="ai-provider-name">Name</Label>
              <Input id="ai-provider-name" autoComplete="off" {...register("name")} />
              {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="ai-provider-select">Provider</Label>
              <Select
                value={provider}
                onValueChange={(value) => {
                  if (!value) return;
                  const next = value as AiProvider;
                  setProvider(next);
                  setValue("provider", next, { shouldValidate: true });
                }}
              >
                <SelectTrigger id="ai-provider-select" className="w-full">
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
              <Label htmlFor="ai-provider-model">Model name</Label>
              <Input
                id="ai-provider-model"
                autoComplete="off"
                placeholder="e.g. claude-sonnet-5"
                {...register("model_name")}
              />
              {errors.model_name && <p className="text-sm text-destructive">{errors.model_name.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="ai-provider-base-url">
                Base URL{SELF_HOSTED_PROVIDERS.includes(provider) ? "" : " (optional)"}
              </Label>
              <Input
                id="ai-provider-base-url"
                placeholder="http://localhost:1234/v1"
                autoComplete="off"
                {...register("base_url")}
              />
              {errors.base_url && <p className="text-sm text-destructive">{errors.base_url.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="ai-provider-api-key">API key</Label>
              <Input
                id="ai-provider-api-key"
                type="password"
                autoComplete="off"
                placeholder={
                  target?.mode === "edit" && target.provider.has_api_key
                    ? "•••• saved — leave blank to keep"
                    : undefined
                }
                {...register("api_key")}
              />
              {errors.api_key && <p className="text-sm text-destructive">{errors.api_key.message}</p>}
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={test.isPending}
              onClick={handleSubmit((values) => test.mutate(buildTestInput(values)))}
            >
              {test.isPending ? "Testing…" : "Test connection"}
            </Button>
            <Button type="submit" disabled={isSaving}>
              {isSaving ? "Saving…" : isEdit ? "Save changes" : "Add provider"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function AiProvidersPanel() {
  const queryClient = useQueryClient();
  const [dialogTarget, setDialogTarget] = useState<DialogTarget | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.ai.providers.all(),
    queryFn: listAiProviders,
  });

  const activate = useMutation({
    mutationFn: (id: string) => activateAiProvider(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.ai.providers.all() });
      queryClient.invalidateQueries({ queryKey: queryKeys.ai.status() });
      toast.success("Provider activated");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to activate provider"),
  });

  const deactivate = useMutation({
    mutationFn: () => deactivateAiProvider(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.ai.providers.all() });
      queryClient.invalidateQueries({ queryKey: queryKeys.ai.status() });
      toast.success("Provider deactivated");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to deactivate provider"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteAiProvider(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.ai.providers.all() });
      queryClient.invalidateQueries({ queryKey: queryKeys.ai.status() });
      toast.success("Provider deleted");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to delete provider"),
  });

  const test = useMutation({
    mutationFn: (input: TestAiProviderInput) => testAiProviderConnection(input),
    onSuccess: () => toast.success("Connection successful"),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Connection test failed"),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Configure one or more AI providers for finding analysis. Only one provider is active at a time.
        </p>
        <Button onClick={() => setDialogTarget({ mode: "create" })}>Add provider</Button>
      </div>
      <DataTableCard
        isLoading={isLoading}
        isError={false}
        isEmpty={!!data && data.length === 0}
        emptyState={
          <EmptyState
            icon={Sparkles}
            title="No AI providers configured"
            description="Add a provider to enable AI-assisted finding analysis."
            action={<Button onClick={() => setDialogTarget({ mode: "create" })}>Add provider</Button>}
          />
        }
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Provider / Model</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Usage</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.map((p) => (
              <TableRow key={p.id}>
                <TableCell>{p.name}</TableCell>
                <TableCell>
                  <div className="space-y-1">
                    <Badge variant="secondary">{PROVIDER_LABELS[p.provider]}</Badge>
                    <p className="font-mono text-xs text-muted-foreground">{p.model_name ?? "—"}</p>
                  </div>
                </TableCell>
                <TableCell>
                  {p.is_active ? (
                    <Badge className="bg-green-600 text-white">Active</Badge>
                  ) : (
                    <Button
                      size="sm"
                      onClick={() => activate.mutate(p.id)}
                      disabled={activate.isPending && activate.variables === p.id}
                    >
                      {activate.isPending && activate.variables === p.id ? "Activating…" : "Set Active"}
                    </Button>
                  )}
                </TableCell>
                <TableCell>
                  <div className="space-y-0.5 text-xs">
                    <p>
                      {p.total_requests} req
                      {p.total_failed_requests > 0 ? `, ${p.total_failed_requests} failed` : ""}
                    </p>
                    <p className="text-muted-foreground">
                      {tokenFormatter.format(p.total_prompt_tokens + p.total_completion_tokens)} tokens ·{" "}
                      {costFormatter.format(p.total_cost_usd)}
                    </p>
                    <p className="text-muted-foreground">
                      {p.last_used_at ? formatRelativeTime(p.last_used_at) : "Never used"}
                    </p>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        test.mutate({
                          id: p.id,
                          provider: p.provider,
                          model_name: p.model_name ?? "",
                          base_url: p.base_url ?? undefined,
                        })
                      }
                      disabled={test.isPending && test.variables?.id === p.id}
                    >
                      {test.isPending && test.variables?.id === p.id ? "Testing…" : "Test"}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setDialogTarget({ mode: "edit", provider: p })}
                    >
                      Edit
                    </Button>
                    {p.is_active && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => deactivate.mutate()}
                        disabled={deactivate.isPending}
                      >
                        {deactivate.isPending ? "Deactivating…" : "Deactivate"}
                      </Button>
                    )}
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => remove.mutate(p.id)}
                      disabled={remove.isPending && remove.variables === p.id}
                    >
                      Delete
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DataTableCard>
      <AiProviderDialog target={dialogTarget} onClose={() => setDialogTarget(null)} />
    </div>
  );
}

export default function AiProviderSettingsPage() {
  const isAdmin = useHasRole("admin");
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">AI Provider</h2>
        <p className="text-sm text-muted-foreground">
          Configure the AI providers used for finding analysis.
        </p>
      </div>
      <RequireRole role="admin">
        <AiProvidersPanel />
      </RequireRole>
      {!isAdmin && (
        <EmptyState
          icon={Sparkles}
          title="Admins only"
          description="Only admins can configure the AI provider."
        />
      )}
    </div>
  );
}
