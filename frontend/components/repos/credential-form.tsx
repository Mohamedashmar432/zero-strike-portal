"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { createRepoCredential, type Provider, type RepoCredential } from "@/lib/api/repo-credentials";
import {
  normalizeAdoOrganization,
  repoCredentialSchema,
  type RepoCredentialInput,
} from "@/lib/validation/repo-credential.schema";

const PROVIDERS: { value: Provider; label: string }[] = [
  { value: "github", label: "GitHub" },
  { value: "azure_devops", label: "Azure DevOps" },
];

export function CredentialForm({
  provider: fixedProvider,
  onCreated,
}: {
  provider?: Provider;
  onCreated: (credential: RepoCredential) => void;
}) {
  const queryClient = useQueryClient();
  const [provider, setProvider] = useState<Provider>(fixedProvider ?? "github");
  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<RepoCredentialInput>({
    resolver: zodResolver(repoCredentialSchema),
    defaultValues: { provider: fixedProvider ?? "github" },
  });

  const create = useMutation({
    mutationFn: (values: RepoCredentialInput) =>
      createRepoCredential(
        values.provider === "azure_devops"
          ? { ...values, organization: normalizeAdoOrganization(values.organization) }
          : values
      ),
    onSuccess: (credential) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.repoCredentials.all() });
      toast.success("Credential saved");
      onCreated(credential);
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Failed to validate and save credential"),
  });

  return (
    <form onSubmit={handleSubmit((values) => create.mutate(values))} className="space-y-4">
      {!fixedProvider && (
        <div className="space-y-2">
          <Label>Provider</Label>
          <Select
            value={provider}
            onValueChange={(value) => {
              const next = value as Provider;
              setProvider(next);
              setValue("provider", next);
            }}
          >
            <SelectTrigger className="w-full">
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
      )}
      <div className="space-y-2">
        <Label htmlFor="cred-org">{provider === "azure_devops" ? "Organization" : "Owner / organization"}</Label>
        <Input
          id="cred-org"
          autoComplete="off"
          placeholder={provider === "azure_devops" ? "my-org or https://dev.azure.com/my-org" : undefined}
          {...register("organization")}
        />
        {errors.organization && <p className="text-sm text-destructive">{errors.organization.message}</p>}
      </div>
      <div className="space-y-2">
        <Label htmlFor="cred-pat">Personal access token</Label>
        {/* new-password: "off" does not stop Chrome filling a saved site login into a PAT field. */}
        <Input id="cred-pat" type="password" autoComplete="new-password" {...register("pat")} />
        {errors.pat && <p className="text-sm text-destructive">{errors.pat.message}</p>}
        {provider === "azure_devops" && (
          <p className="text-xs text-muted-foreground">
            Needs <span className="font-mono">Project and Team: Read</span> and{" "}
            <span className="font-mono">Code: Read</span> (add <span className="font-mono">Code: Read &amp; write</span>{" "}
            for auto-fix PRs). You&apos;ll pick the project, repo and branch next.
          </p>
        )}
      </div>
      <div className="space-y-2">
        <Label htmlFor="cred-label">Label (optional)</Label>
        <Input
          id="cred-label"
          placeholder={provider === "azure_devops" ? "e.g. Work Azure DevOps" : "e.g. Personal GitHub"}
          autoComplete="off"
          {...register("label")}
        />
      </div>
      <Button type="submit" disabled={create.isPending}>
        {create.isPending ? "Validating…" : "Save & validate"}
      </Button>
    </form>
  );
}
