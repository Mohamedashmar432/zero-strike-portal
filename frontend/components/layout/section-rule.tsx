import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Section divider in instrument-legend form: a mono micro-label, then a hairline
 * that runs out to the right edge, then optional controls.
 *
 * Replaces the "icon tinted brand-color + 14px semibold heading + bottom border"
 * pattern that every generated dashboard uses for section headers. The rule
 * doing the work instead of a heavier font weight is what keeps a page of eight
 * sections from looking like eight competing titles.
 */
export function SectionRule({
  label,
  icon: Icon,
  actions,
  className,
}: {
  label: string;
  icon?: LucideIcon;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <div className="flex shrink-0 items-center gap-2">
        {Icon && <Icon className="size-3.5 text-muted-foreground" aria-hidden="true" />}
        <h2 className="legend text-foreground">{label}</h2>
      </div>
      <div className="h-px flex-1 bg-hairline" />
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
