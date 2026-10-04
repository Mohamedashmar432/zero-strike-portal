import { Badge } from "@/components/ui/badge";
import type { AiProviderConfig } from "@/lib/api/ai";

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
