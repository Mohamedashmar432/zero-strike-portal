import type { LiveAlertDelivery } from "@/lib/api/live-alerts";
import { deliveryChips, type ChipTone } from "@/lib/live-alerts";
import { cn } from "@/lib/utils";

const TONE: Record<ChipTone, string> = {
  ok: "border-border text-foreground",
  bad: "border-severity-critical text-severity-critical",
  muted: "border-border text-muted-foreground",
};

/** Recorded delivery outcomes for one live alert. Reads "sent" only when the outcome is "sent". */
export function DeliveryChips({ delivery }: { delivery: LiveAlertDelivery }) {
  return (
    <ul className="flex flex-wrap gap-1">
      {deliveryChips(delivery).map((c) => (
        <li
          key={c.label}
          className={cn("rounded-sm border px-1.5 py-0.5 font-mono text-[10px] leading-none", TONE[c.tone])}
        >
          {c.label}
        </li>
      ))}
    </ul>
  );
}
