import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Empty state as an unpopulated instrument slot: a dashed hairline frame with a
 * mono legend. Reads as "this channel has no signal yet" rather than as a
 * broken card, and is visually distinct from a populated panel — which the old
 * version wasn't, since it used the same solid Card chrome as real content.
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "m-3 flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-hairline px-6 py-10 text-center",
        className
      )}
    >
      {Icon && (
        <Icon className="mb-1 size-6 text-muted-foreground/50" strokeWidth={1.5} aria-hidden="true" />
      )}
      <p className="legend text-foreground">{title}</p>
      {description && (
        <p className="max-w-[46ch] text-[13px] leading-relaxed text-muted-foreground">
          {description}
        </p>
      )}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}
