"use client";

import { useState } from "react";
import { EmptyState } from "@/components/common/empty-state";
import { CredentialForm } from "@/components/repos/credential-form";
import { IntegrationsTable } from "@/components/settings/integrations/integrations-table";
import { useCredentialIntegrations } from "@/components/settings/integrations/use-credential-integrations";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function SourceControlPage() {
  const [adding, setAdding] = useState(false);
  const { rows, isLoading, isError, dialogs } = useCredentialIntegrations();

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-2xl text-sm text-muted-foreground">
          Save a GitHub or Azure DevOps Personal Access Token here, then use it to connect repos on any project&apos;s
          Repositories tab. Each project connection keeps its own copy of the credential, so connecting one project to a
          different account never affects another project.
        </p>
        {!adding && <Button onClick={() => setAdding(true)}>Add credential</Button>}
      </div>
      {adding && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Add credential</CardTitle>
          </CardHeader>
          <CardContent className="max-w-md space-y-4">
            <CredentialForm onCreated={() => setAdding(false)} />
            <Button variant="ghost" size="sm" onClick={() => setAdding(false)}>
              Cancel
            </Button>
          </CardContent>
        </Card>
      )}
      <IntegrationsTable
        rows={rows}
        isLoading={isLoading}
        isError={isError}
        emptyState={
          <EmptyState
            title="No credentials saved"
            description="Add a Personal Access Token to get started."
            action={<Button onClick={() => setAdding(true)}>Add credential</Button>}
          />
        }
      />
      {dialogs}
    </div>
  );
}
