import { FlaskConical } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Marks a surface as a design preview with no engine behind it.
 *
 * This exists because the DAST and Attack Simulation tabs shipped fabricated
 * telemetry — invented target hostnames, endpoint counts, and a fake
 * "scan completed, 0 critical blockers" toast — while the backend has no such
 * endpoints at all. In a security product an unmarked mockup is not a harmless
 * placeholder: a screenshot of it reads as evidence that a scan ran.
 *
 * Keep the mockup, remove the claim.
 */
export function PreviewNotice({
  feature,
  className,
}: {
  feature: string;
  className?: string;
}) {
  return (
    <div
      role="note"
      className={cn(
        "flex items-start gap-2.5 rounded-sm border border-dashed border-severity-medium/60 bg-severity-medium-tint px-3 py-2.5",
        className
      )}
    >
      <FlaskConical className="mt-px size-4 shrink-0 text-severity-medium" aria-hidden="true" />
      <div className="min-w-0">
        <p className="legend text-severity-medium">Preview · not live data</p>
        <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">
          {feature} has no scan engine connected yet. Everything below is
          illustrative sample content for layout review — it is not a result, and
          nothing here reflects the security state of this project.
        </p>
      </div>
    </div>
  );
}
