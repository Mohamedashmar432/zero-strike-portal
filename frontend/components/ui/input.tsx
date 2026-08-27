import * as React from "react"
import { Input as InputPrimitive } from "@base-ui/react/input"

import { cn } from "@/lib/utils"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <InputPrimitive
      type={type}
      data-slot="input"
      className={cn(
        // Mono inputs. Nearly every field in this app holds something you'd
        // read character-by-character — repo URLs, branch names, API keys, file
        // globs, CVE ids — so proportional type is actively worse here. 16px on
        // mobile (`text-base`) prevents iOS zoom-on-focus; 13px from md up.
        "h-8 w-full min-w-0 rounded-lg border border-input bg-background px-2.5 py-1 font-mono text-base transition-colors outline-none file:inline-flex file:h-6 file:border-0 file:bg-transparent file:font-sans file:text-sm file:font-medium file:text-foreground placeholder:font-sans placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40 disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60 aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/30 md:text-[13px] dark:aria-invalid:border-destructive/50",
        className
      )}
      {...props}
    />
  )
}

export { Input }
