"use client";

import { useEffect, useLayoutEffect, useRef } from "react";
import { HL } from "./kernel";
import { hunter } from "./hunter";
import type { ScanStage } from "@/lib/api/scans";

const STAGE_INDEX: Record<ScanStage, number> = { validating: 0, cloning: 1, scanning: 2, ingesting: 3 };

/**
 * The scan pipeline as a loupe hunting through rows of code (see hairline-hunter.html,
 * built with the hairline-create skill: .claude/skills/hairline-create/hunter.js is the
 * source figure). Unlike the package's pointer-driven figures, this one is driven by
 * `stage` -- a cloud scan runs on the server, so there is no hand on this page to answer,
 * and `goto()` (added to mount()'s return value for this reason) takes the same row index
 * the pointer would have picked. Row 2 (the scan phase) is the one that hides a flagged
 * line -- the scanner catching something -- matching what that phase actually does.
 */
export function HunterFigure({ stage, className }: { stage: ScanStage | null; className?: string }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const handleRef = useRef<{ goto: (i: number) => void; destroy: () => void } | null>(null);

  useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    HL.inject(document);
    host.setAttribute("data-hairline", hunter.name);
    host.setAttribute("role", "img");
    host.setAttribute("aria-label", hunter.means);
    const svg = HL.mk("svg", { viewBox: "0 0 400 320", "aria-hidden": "true" }, host);
    let caption = "";
    const read = {
      get textContent() { return caption; },
      set textContent(v: string) { caption = v ?? ""; },
    };
    const [, mid] = hunter.range;
    handleRef.current = hunter.mount(HL, { stage: host, svg, read }, mid);
    return () => {
      handleRef.current?.destroy();
      handleRef.current = null;
    };
    // Mounts once, like the package's own components; `stage` updates go through goto() below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    handleRef.current?.goto(stage ? STAGE_INDEX[stage] : -1);
  }, [stage]);

  return <div ref={hostRef} className={className} style={{ aspectRatio: "5 / 4", width: "100%" }} />;
}
