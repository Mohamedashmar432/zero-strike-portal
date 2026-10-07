"use client";

import { Combobox } from "@base-ui/react/combobox";
import { CheckIcon, ChevronDownIcon, XIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type SearchableOption = { value: string; label: string; hint?: string | null };

// A dropdown you can type into: the input filters the list, arrow keys + Enter pick. Built on Base
// UI's Combobox so focus, keyboard and ARIA behave like the rest of the shadcn controls.
export function SearchableSelect({
  id,
  options,
  value,
  onValueChange,
  placeholder = "Search…",
  emptyText = "No matches.",
  loading = false,
  disabled = false,
  // Thousands of branches render fine once filtered; only the unfiltered list needs a cap.
  limit = 200,
}: {
  id?: string;
  options: SearchableOption[] | undefined;
  value: string | null;
  onValueChange: (value: string | null) => void;
  placeholder?: string;
  emptyText?: string;
  loading?: boolean;
  disabled?: boolean;
  limit?: number;
}) {
  const items = options ?? [];
  const selected = items.find((o) => o.value === value) ?? null;

  return (
    <Combobox.Root
      items={items}
      value={selected}
      onValueChange={(next) => onValueChange((next as SearchableOption | null)?.value ?? null)}
      itemToStringLabel={(o: SearchableOption) => o.label}
      isItemEqualToValue={(a: SearchableOption, b: SearchableOption) => a.value === b.value}
      disabled={disabled || loading}
      limit={limit}
      autoHighlight
    >
      <Combobox.InputGroup
        className={cn(
          "relative flex h-8 w-full items-center rounded-lg border border-input bg-transparent text-sm transition-colors",
          "focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50 dark:bg-input/30",
          "data-disabled:cursor-not-allowed data-disabled:opacity-50"
        )}
      >
        <Combobox.Input
          id={id}
          placeholder={loading ? "Loading…" : placeholder}
          className="h-full min-w-0 flex-1 bg-transparent pr-14 pl-2.5 outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
        />
        <div className="absolute right-1 flex items-center text-muted-foreground">
          {selected && (
            <Combobox.Clear
              aria-label="Clear selection"
              className="flex size-6 items-center justify-center rounded hover:text-foreground"
            >
              <XIcon className="size-3.5" />
            </Combobox.Clear>
          )}
          <Combobox.Trigger
            aria-label="Open list"
            className="flex size-6 items-center justify-center rounded hover:text-foreground"
          >
            <ChevronDownIcon className="size-4" />
          </Combobox.Trigger>
        </div>
      </Combobox.InputGroup>

      <Combobox.Portal>
        <Combobox.Positioner sideOffset={4} className="isolate z-50">
          <Combobox.Popup className="max-h-[min(20rem,var(--available-height))] w-(--anchor-width) overflow-hidden rounded-lg bg-popover text-popover-foreground shadow-md ring-1 ring-foreground/10 data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0">
            <Combobox.Empty className="px-2.5 py-2 text-sm text-muted-foreground empty:hidden">
              {emptyText}
            </Combobox.Empty>
            <Combobox.List className="max-h-[min(20rem,var(--available-height))] overflow-y-auto overscroll-contain p-1 data-empty:p-0">
              {(o: SearchableOption) => (
                <Combobox.Item
                  key={o.value}
                  value={o}
                  className="relative flex cursor-default items-center gap-2 rounded-md py-1.5 pr-8 pl-2 text-sm outline-none select-none data-highlighted:bg-accent data-highlighted:text-accent-foreground"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{o.label}</span>
                    {o.hint && <span className="block truncate text-xs text-muted-foreground">{o.hint}</span>}
                  </span>
                  <Combobox.ItemIndicator className="absolute right-2 flex size-4 items-center justify-center">
                    <CheckIcon className="size-4" />
                  </Combobox.ItemIndicator>
                </Combobox.Item>
              )}
            </Combobox.List>
          </Combobox.Popup>
        </Combobox.Positioner>
      </Combobox.Portal>
    </Combobox.Root>
  );
}
