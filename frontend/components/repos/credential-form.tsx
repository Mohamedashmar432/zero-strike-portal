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
import { createRepoCredential, type Provider, type RepoCredential } from "@/lib/api/repo-credentials";
import { repoCredentialSchema, type RepoCredentialInput } from "@/lib/validation/repo-credential.schema";

const PROVIDERS: { value: Provider; label: string }[] = [
  { value: "github", label: "GitHub" },
  { value: "azure_devops", label: "Azure DevOps" },
];

export function CredentialForm({ onCreated }: { onCreated: (credential: RepoCredential) => void }) {
  const queryClient = useQueryClient();
  const [provider, setProvider] = useState<Provider>("github");
  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<RepoCredentialInput>({
    resolver: zodResolver(repoCredentialSchema),
    defaultValues: { provider: "github" },
  });

  const create = useMutation({
    mutationFn: (values: RepoCredentialInput) => createRepoCredential(values),
    onSuccess: (credential) => {
      queryClient.invalidateQueries({ queryKey: ["repo-credentials"] });
      toast.success("Credential saved");
      onCreated(credential);
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Failed to validate and save credential"),
  });

  return (
    <form onSubmit={handleSubmit((values) => create.mutate(values))} className="space-y-4">
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
      <div className="space-y-2">
        <Label htmlFor="cred-org">{provider === "azure_devops" ? "Organization" : "Owner / organization"}</Label>
        <Input id="cred-org" autoComplete="off" {...register("organization")} />
        {errors.organization && <p className="text-sm text-destructive">{errors.organization.message}</p>}
      </div>
      {provider === "azure_devops" && (
        <div className="space-y-2">
          <Label htmlFor="cred-ado-project">Azure DevOps project</Label>
          <Input id="cred-ado-project" autoComplete="off" {...register("ado_project")} />
          {errors.ado_project && <p className="text-sm text-destructive">{errors.ado_project.message}</p>}
        </div>
      )}
      <div className="space-y-2">
        <Label htmlFor="cred-pat">Personal access token</Label>
        <Input id="cred-pat" type="password" autoComplete="off" {...register("pat")} />
        {errors.pat && <p className="text-sm text-destructive">{errors.pat.message}</p>}
      </div>
      <div className="space-y-2">
        <Label htmlFor="cred-label">Label (optional)</Label>
        <Input id="cred-label" placeholder="e.g. Personal GitHub" autoComplete="off" {...register("label")} />
      </div>
      <Button type="submit" disabled={create.isPending}>
        {create.isPending ? "Validating…" : "Save & validate"}
      </Button>
    </form>
  );
}
