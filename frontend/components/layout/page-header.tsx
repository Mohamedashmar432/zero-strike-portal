import type { ReactNode } from "react";

/**
 * Page header. The title is mono — same face as the metric readouts and badges,
 * so a page title reads as a channel name on an instrument rather than as
 * marketing copy. `eyebrow` gives pages a mono kicker above the title (e.g.
 * "PROJECT / api-gateway") which is where the old design had nothing, so every
 * page opened identically.
 */
export function PageHeader({
  title,
  description,
  actions,
  breadcrumb,
  eyebrow,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  breadcrumb?: ReactNode;
  eyebrow?: string;
}) {
  return (
    <div className="space-y-2">
      {breadcrumb}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          {eyebrow && <p className="legend mb-1.5 text-muted-foreground">{eyebrow}</p>}
          <h1 className="font-mono text-2xl font-bold tracking-[-0.035em] text-foreground">
            {title}
          </h1>
          {description && (
            <p className="mt-1.5 max-w-[70ch] text-sm leading-relaxed text-muted-foreground">
              {description}
            </p>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}
