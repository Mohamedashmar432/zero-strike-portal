"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { CredentialForm } from "@/components/repos/credential-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError } from "@/lib/api/client";
import { deleteRepoCredential, listRepoCredentials } from "@/lib/api/repo-credentials";

export default function IntegrationsPage() {
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const { data: credentials, isLoading, isError } = useQuery({
    queryKey: ["repo-credentials"],
    queryFn: listRepoCredentials,
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteRepoCredential(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["repo-credentials"] });
      toast.success("Credential removed");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to remove credential"),
  });

  return (
    <div className="max-w-md space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Integrations</h2>
        <p className="text-sm text-muted-foreground">Saved GitHub and Azure DevOps credentials.</p>
      </div>
      <p className="text-sm text-muted-foreground">
        Save a GitHub or Azure DevOps Personal Access Token here, then use it to connect repos on any
        project&apos;s Repositories tab. Each project connection keeps its own copy of the credential, so
        connecting one project to a different account never affects another project.
      </p>
      <DataTableCard
        bare
        isLoading={isLoading}
        isError={isError}
        errorMessage="Failed to load credentials."
        isEmpty={!!credentials && credentials.length === 0 && !adding}
        emptyState={
          <EmptyState
            title="No credentials saved"
            description="Add a Personal Access Token to get started."
            action={<Button onClick={() => setAdding(true)}>Add credential</Button>}
          />
        }
      >
        <div className="space-y-4">
          {credentials?.map((c) => (
            <Card key={c.id}>
              <CardHeader>
                <CardTitle className="flex items-center justify-between text-base">
                  <span>{c.label || (c.provider === "azure_devops" ? "Azure DevOps" : "GitHub")}</span>
                  <Badge variant="secondary" className="font-mono">
                    {c.organization}
                    {c.ado_project ? ` / ${c.ado_project}` : ""}
                  </Badge>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => remove.mutate(c.id)}
                  disabled={remove.isPending}
                >
                  Remove
                </Button>
              </CardContent>
            </Card>
          ))}
          {adding ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Add credential</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <CredentialForm onCreated={() => setAdding(false)} />
                <Button variant="ghost" size="sm" onClick={() => setAdding(false)}>
                  Cancel
                </Button>
              </CardContent>
            </Card>
          ) : (
            credentials &&
            credentials.length > 0 && (
              <Button variant="outline" onClick={() => setAdding(true)}>
                Add credential
              </Button>
            )
          )}
        </div>
      </DataTableCard>
    </div>
  );
}
