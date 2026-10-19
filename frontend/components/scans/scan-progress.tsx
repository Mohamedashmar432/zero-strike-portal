"use client";

import { Check } from "lucide-react";
import { useEffect, useState } from "react";
import { HunterFigure } from "@/lib/hairline/hunter-figure";
import { SCAN_STAGE_LABELS, type ScanStage } from "@/lib/api/scans";
import { cn, parseApiDate } from "@/lib/utils";

const STAGES: ScanStage[] = ["validating", "cloning", "scanning", "ingesting"];

function clock(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// ponytail: the backend reports the phase, not a percentage (the scanner subprocess emits no
// progress), so this shows the real phase and real elapsed time rather than an invented bar.
export function ScanProgress({
  stage,
  stageStartedAt,
  startedAt,
}: {
  stage: ScanStage | null;
  stageStartedAt: string | null;
  startedAt: string | null;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const active = stage ? STAGES.indexOf(stage) : -1;
  const since = (iso: string | null) => (iso ? clock(now - parseApiDate(iso).getTime()) : "—");

  return (
    <div className="grid gap-6 rounded-lg border bg-card p-6 md:grid-cols-[minmax(0,320px)_1fr] md:items-center">
      <div
        aria-hidden
        // Plates are filled, so they must match the card they sit on.
        style={
          {
            "--hairline-plate": "var(--card)",
            "--hairline-hi": "var(--primary)",
            "--hairline-edge": "var(--foreground)",
            "--hairline-mid": "var(--muted-foreground)",
            "--hairline-lo": "var(--border)",
          } as React.CSSProperties
        }
      >
        <HunterFigure stage={stage} />
      </div>

      <div>
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">Scan in progress</p>
        <h2 className="mt-1 text-xl font-semibold">{stage ? SCAN_STAGE_LABELS[stage] : "Waiting for the scanner…"}</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          This page updates automatically — no need to refresh.
          {stage && <> Step {active + 1} of {STAGES.length}.</>}
        </p>

        <ol className="mt-5 space-y-2">
          {STAGES.map((s, i) => {
            const done = i < active;
            const current = i === active;
            return (
              <li key={s} className="flex items-center gap-3 text-sm">
                <span
                  className={cn(
                    "flex size-5 items-center justify-center rounded-full border text-[10px]",
                    done && "border-primary bg-primary text-primary-foreground",
                    current && "border-primary text-primary",
                  )}
                >
                  {done ? <Check className="size-3" /> : i + 1}
                </span>
                <span className={cn(!done && !current && "text-muted-foreground", current && "font-medium")}>
                  {SCAN_STAGE_LABELS[s]}
                </span>
                {current && (
                  <span className="ml-auto font-mono text-xs text-muted-foreground">{since(stageStartedAt)}</span>
                )}
              </li>
            );
          })}
        </ol>

        <p className="mt-4 font-mono text-xs text-muted-foreground">Total elapsed {since(startedAt)}</p>
      </div>
    </div>
  );
}
