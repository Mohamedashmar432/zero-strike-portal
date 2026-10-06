"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

/** A command block with a copy button — the one interactive piece a server-rendered doc page needs. */
export function CopyCommand({ children }: { children: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="group relative">
      <pre className="overflow-x-auto rounded-sm border border-border bg-muted py-2 pr-11 pl-3 font-mono text-[12px] leading-relaxed text-foreground">
        {children}
      </pre>
      <button
        type="button"
        aria-label={copied ? "Copied" : "Copy command"}
        onClick={() => {
          navigator.clipboard.writeText(children).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          });
        }}
        className="absolute top-1.5 right-1.5 grid size-7 place-items-center rounded-sm border border-border bg-background text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-signal"
      >
        {copied ? <Check className="size-3.5 text-primary" /> : <Copy className="size-3.5" />}
      </button>
    </div>
  );
}
