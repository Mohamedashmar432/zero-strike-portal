"use client";

import { Combobox } from "@base-ui/react/combobox";
import { CheckIcon, ChevronDownIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type FilterOption = { value: string; label: string; count: number | null };

// A collapsed, searchable, multi-select dropdown for filters with many values (repository, rule,
// assignee). The list lives in a popup, so it can never push the sidebar taller or spill over the
// table; the picked values are shown as chips above the table, so the field only needs a count.
export function MultiSelectFilter({
  title,
  options,
  selected,
  onToggle,
}: {
  title: string;
  options: FilterOption[];
  selected: string[];
  onToggle: (value: string) => void;
}) {
  if (options.length === 0) return null;
  const value = options.filter((o) => selected.includes(o.value));
  return (
    <div className="min-w-0 space-y-1">
      <p className="legend text-muted-foreground">{title}</p>
      <Combobox.Root
        multiple
        items={options}
        value={value}
        // Base UI hands back the whole next array; diff it against the URL-backed selection and toggle
        // the one value that changed, so the URL stays the single source of truth.
        onValueChange={(next) => {
          const nextValues = (next as FilterOption[]).map((o) => o.value);
          const changed = [...nextValues.filter((v) => !selected.includes(v)), ...selected.filter((v) => !nextValues.includes(v))];
          if (changed[0] !== undefined) onToggle(changed[0]);
        }}
        itemToStringLabel={(o: FilterOption) => o.label}
        isItemEqualToValue={(a: FilterOption, b: FilterOption) => a.value === b.value}
        autoHighlight
      >
        <Combobox.InputGroup className="relative flex h-8 w-full items-center rounded-lg border border-input bg-transparent text-xs transition-colors focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50 dark:bg-input/30">
          <Combobox.Input
            aria-label={`Filter by ${title.toLowerCase()}`}
            placeholder={selected.length ? `${selected.length} selected — search…` : `Any ${title.toLowerCase()} — search…`}
            className="h-full min-w-0 flex-1 bg-transparent pr-8 pl-2.5 outline-none placeholder:text-muted-foreground"
          />
          <Combobox.Trigger
            aria-label={`Open ${title.toLowerCase()} list`}
            className="absolute right-1 flex size-6 items-center justify-center rounded text-muted-foreground hover:text-foreground"
          >
            <ChevronDownIcon className="size-4" />
          </Combobox.Trigger>
        </Combobox.InputGroup>

        <Combobox.Portal>
          <Combobox.Positioner sideOffset={4} className="isolate z-50">
            <Combobox.Popup className="max-h-[min(20rem,var(--available-height))] w-[max(var(--anchor-width),18rem)] overflow-hidden rounded-lg bg-popover text-popover-foreground shadow-md ring-1 ring-foreground/10">
              <Combobox.Empty className="px-2.5 py-2 text-xs text-muted-foreground empty:hidden">No matches.</Combobox.Empty>
              <Combobox.List className="max-h-[min(20rem,var(--available-height))] overflow-y-auto overscroll-contain p-1 data-empty:p-0">
                {(o: FilterOption) => (
                  <Combobox.Item
                    key={o.value}
                    value={o}
                    className={cn(
                      "relative flex cursor-default items-center gap-2 rounded-md py-1.5 pr-2 pl-7 text-xs outline-none select-none",
                      "data-highlighted:bg-accent data-highlighted:text-accent-foreground"
                    )}
                  >
                    <Combobox.ItemIndicator className="absolute left-2 flex size-4 items-center justify-center">
                      <CheckIcon className="size-3.5" />
                    </Combobox.ItemIndicator>
                    <span className="min-w-0 flex-1 truncate" title={o.label}>
                      {o.label}
                    </span>
                    {o.count !== null && (
                      <span className="font-mono text-[11px] tabular-nums text-muted-foreground">{o.count.toLocaleString()}</span>
                    )}
                  </Combobox.Item>
                )}
              </Combobox.List>
            </Combobox.Popup>
          </Combobox.Positioner>
        </Combobox.Portal>
      </Combobox.Root>
    </div>
  );
}
