import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Multi-line input. Mirrors ui/input.tsx: control-boundary border (>=3:1 per
 * WCAG 2.2 SC 1.4.11), 16px on mobile to stop iOS zoom-on-focus, 13px from md up.
 *
 * Body text here is prose a human writes, so unlike Input this stays on the sans
 * face — mono is for identifiers, not sentences.
 */
function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "min-h-20 w-full resize-y rounded-lg border border-input bg-background px-2.5 py-2 text-base leading-relaxed transition-colors outline-none",
        "placeholder:text-muted-foreground",
        "focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40",
        "disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60",
        "aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/30",
        "md:text-[13px]",
        className
      )}
      {...props}
    />
  );
}

export { Textarea };
