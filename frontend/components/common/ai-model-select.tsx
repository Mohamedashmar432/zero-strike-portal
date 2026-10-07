"use client";

import { useQuery } from "@tanstack/react-query";

import { getAiModelCatalog, type AiProvider } from "@/lib/api/ai";
import { queryKeys } from "@/lib/api/query-keys";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

/**
 * Model picker for an AI provider form. The ids come from the backend catalog, which is the exact
 * string each provider's API expects, so a user cannot mistype one. A provider the catalog has no
 * list for (custom, commandcode) -- or a catalog that failed to load -- falls back to a text box.
 */
export function AiModelSelect({
  id,
  provider,
  value,
  onChange,
}: {
  id: string;
  provider: AiProvider;
  value: string;
  onChange: (model: string) => void;
}) {
  const catalog = useQuery({
    queryKey: queryKeys.ai.models(),
    queryFn: getAiModelCatalog,
    staleTime: 60 * 60 * 1000,
  });
  const models = catalog.data?.[provider] ?? [];

  if (models.length === 0) {
    return (
      <Input
        id={id}
        autoComplete="off"
        value={value}
        placeholder="Model id, exactly as the provider names it"
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  // A saved model that has since left the catalog must still show, not silently blank.
  const options = value && !models.includes(value) ? [value, ...models] : models;
  return (
    <Select value={value || null} onValueChange={(v) => v && onChange(v)}>
      <SelectTrigger id={id} className="w-full">
        <SelectValue placeholder="Select a model" />
      </SelectTrigger>
      <SelectContent>
        {options.map((m) => (
          <SelectItem key={m} value={m}>
            {m}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
