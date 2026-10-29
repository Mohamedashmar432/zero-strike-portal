"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { InsightsRange } from "@/lib/api/project-insights";
import { parseApiDate } from "@/lib/utils";

const PRESETS = [
  { value: "24h", label: "24h", days: 1 },
  { value: "7d", label: "7d", days: 7 },
  { value: "30d", label: "30d", days: 30 },
  { value: "90d", label: "90d", days: 90 },
] as const;
type Preset = (typeof PRESETS)[number]["value"] | "custom";

// Mirrors the backend cap.
const MAX_RANGE_DAYS = 366;

/** YYYY-MM-DD in the admin's own timezone — what <input type="date"> reads and writes. */
const localDay = (d = new Date()) => d.toLocaleDateString("en-CA");

function presetRange(days: number): InsightsRange {
  const until = new Date();
  return { since: new Date(until.getTime() - days * 86_400_000).toISOString(), until: until.toISOString() };
}

/** Whole local days [from 00:00, to + 1 day 00:00), as the UTC instants the API filters on. */
function customRange(from: string, to: string): InsightsRange | string {
  const start = new Date(`${from}T00:00`);
  const end = new Date(`${to}T00:00`);
  end.setDate(end.getDate() + 1);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return "Pick both dates.";
  if (end <= start) return "The end date must be on or after the start date.";
  if (end.getTime() - start.getTime() > MAX_RANGE_DAYS * 86_400_000)
    return `A range can span at most ${MAX_RANGE_DAYS} days.`;
  return { since: start.toISOString(), until: end.toISOString() };
}

export const fmt = (n: number) => n.toLocaleString();
export const when = (iso: string | null) => (iso ? parseApiDate(iso).toLocaleString() : "—");

/** The one date filter every Control Panel tab shares. `range` is null while a custom range is invalid. */
export function useDateRange() {
  const [preset, setPreset] = useState<Preset>("30d");
  const [fixed, setFixed] = useState<InsightsRange>(() => presetRange(30));
  const [from, setFrom] = useState(() => localDay(new Date(Date.now() - 29 * 86_400_000)));
  const [to, setTo] = useState(() => localDay());

  const custom = preset === "custom" ? customRange(from, to) : null;
  const error = typeof custom === "string" ? custom : null;
  const range: InsightsRange | null = typeof custom === "string" ? null : (custom ?? fixed);
  return { preset, setPreset, setFixed, from, setFrom, to, setTo, range, error };
}

export type DateRangeState = ReturnType<typeof useDateRange>;

export function DateRangeBar({ state, onChange }: { state: DateRangeState; onChange?: () => void }) {
  const { preset, setPreset, setFixed, from, setFrom, to, setTo, error } = state;
  return (
    <div className="flex flex-wrap items-end gap-3">
      <div className="flex gap-1 rounded-lg border border-border p-0.5">
        {PRESETS.map((p) => (
          <Button
            key={p.value}
            size="sm"
            variant={preset === p.value ? "secondary" : "ghost"}
            onClick={() => {
              setPreset(p.value);
              setFixed(presetRange(p.days));
              onChange?.();
            }}
          >
            {p.label}
          </Button>
        ))}
        <Button
          size="sm"
          variant={preset === "custom" ? "secondary" : "ghost"}
          onClick={() => {
            setPreset("custom");
            onChange?.();
          }}
        >
          Custom
        </Button>
      </div>
      {preset === "custom" && (
        <>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            From
            <Input
              type="date"
              value={from}
              max={to}
              onChange={(e) => {
                setFrom(e.target.value);
                onChange?.();
              }}
              className="w-40"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            To
            <Input
              type="date"
              value={to}
              min={from}
              max={localDay()}
              onChange={(e) => {
                setTo(e.target.value);
                onChange?.();
              }}
              className="w-40"
            />
          </label>
        </>
      )}
      {error && <p className="pb-1.5 text-xs text-destructive">{error}</p>}
    </div>
  );
}
