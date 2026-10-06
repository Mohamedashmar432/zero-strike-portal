"use client";

import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { getAiStatus, type AiProviderConfig } from "@/lib/api/ai";
import { queryKeys } from "@/lib/api/query-keys";

/** Where an AI provider key is stored. Only the secret NAME is ever shown, never a value. */
export function KeyStorageBadge({
  storage,
  secretName,
}: {
  storage: AiProviderConfig["key_storage"];
  secretName?: string | null;
}) {
  if (storage === "key_vault") {
    const title = `Stored in Azure Key Vault as ${secretName ?? "(unnamed secret)"}`;
    return (
      <span className="inline-flex items-center gap-1.5" title={title}>
        <Badge variant="secondary">Azure Key Vault</Badge>
        {secretName && (
          <span className="font-mono text-xs text-muted-foreground">{secretName}</span>
        )}
      </span>
    );
  }
  if (storage === "encrypted_database") {
    return (
      <Badge
        variant="outline"
        className="text-muted-foreground"
        title="Not in Key Vault yet. Re-save the key or run scripts/migrate_ai_keys_to_keyvault.py to move it."
      >
        Database (encrypted)
      </Badge>
    );
  }
  return null;
}

/** Under an API key field: where the key will go once saved. The vault switch is deployment-wide,
 *  so the portal-level status answers it for project forms too. Renders nothing until known, so it
 *  never claims Key Vault on a deployment that is not using it. */
export function KeyVaultNote() {
  const { data } = useQuery({ queryKey: queryKeys.ai.status(), queryFn: () => getAiStatus() });
  if (!data) return null;
  if (!data.key_vault_enabled) {
    return <p className="text-xs text-muted-foreground">Stored encrypted in the portal database.</p>;
  }
  return (
    <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
      <Badge variant="secondary" className="gap-1">
        <ShieldCheck className="size-3" />
        Azure Key Vault
      </Badge>
      Every key is stored in Azure Key Vault, never in the database. Only the secret name is shown here.
    </p>
  );
}
