"use client";

import { X } from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { type Chip } from "@/lib/vulnerability-filters";

/**
 * Active filters as removable chips. One tab stop for the whole group (roving tabindex): Left/Right
 * (and Home/End) move between chips, Backspace or Delete removes the focused one and lands on its
 * neighbour so the keyboard never loses its place.
 */
export function FilterChips({
  chips,
  labelFor,
  onRemove,
  onClear,
}: {
  chips: Chip[];
  /** Display text for a chip's raw value (a repo id becomes its name, a user id its email). */
  labelFor: (chip: Chip) => string;
  onRemove: (chip: Chip) => void;
  onClear: () => void;
}) {
  const [active, setActive] = useState(0);
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  if (chips.length === 0) return null;
  const current = Math.min(active, chips.length - 1);

  function focusAt(i: number) {
    const next = Math.max(0, Math.min(chips.length - 1, i));
    setActive(next);
    refs.current[next]?.focus();
  }

  function onKeyDown(e: React.KeyboardEvent, i: number, chip: Chip) {
    if (e.key === "ArrowRight") {
      e.preventDefault();
      focusAt(i + 1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      focusAt(i - 1);
    } else if (e.key === "Home") {
      e.preventDefault();
      focusAt(0);
    } else if (e.key === "End") {
      e.preventDefault();
      focusAt(chips.length - 1);
    } else if (e.key === "Backspace" || e.key === "Delete") {
      e.preventDefault();
      onRemove(chip);
      // The removed chip's slot is taken by its right neighbour (or the new last one).
      const next = Math.min(i, chips.length - 2);
      setActive(Math.max(0, next));
      requestAnimationFrame(() => refs.current[Math.max(0, next)]?.focus());
    }
  }

  return (
    <div role="toolbar" aria-label="Active filters" className="flex flex-wrap items-center gap-1.5">
      {chips.map((chip, i) => (
        <button
          key={`${chip.key}:${chip.value}`}
          ref={(el) => {
            refs.current[i] = el;
          }}
          type="button"
          tabIndex={i === current ? 0 : -1}
          onFocus={() => setActive(i)}
          onKeyDown={(e) => onKeyDown(e, i, chip)}
          onClick={() => onRemove(chip)}
          aria-label={`Remove filter ${chip.group}: ${labelFor(chip)}`}
          className={cn(
            "inline-flex h-6 cursor-pointer items-center gap-1.5 rounded-sm border border-border bg-card px-2 font-mono text-[11px] text-foreground transition-colors",
            "hover:border-signal hover:text-signal focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          )}
        >
          <span className="text-muted-foreground">{chip.group}</span>
          <span className="max-w-48 truncate font-semibold">{labelFor(chip)}</span>
          <X className="size-3" aria-hidden="true" />
        </button>
      ))}
      <Button variant="ghost" size="xs" onClick={onClear}>
        Clear all
      </Button>
    </div>
  );
}
