import { deliverySummary, type AckRecipient } from "@/lib/api/risk-acknowledgements";
import { cn } from "@/lib/utils";

const TONE = {
  sent: "border-status-success bg-status-success-tint text-status-success",
  partial: "border-severity-medium bg-severity-medium-tint text-severity-medium",
  failed: "border-severity-high bg-severity-high-tint text-severity-high",
  not_configured: "border-severity-medium bg-severity-medium-tint text-severity-medium",
  pending: "border-border bg-muted text-muted-foreground",
} as const;

/** Delivery of a batch (or one recipient). "SENT" appears only when a recipient's delivery is `sent`. */
export function DeliveryChip({ recipients }: { recipients: Pick<AckRecipient, "delivery">[] }) {
  const s = deliverySummary(recipients);
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm border-l-2 px-1.5 py-0.5 font-mono text-[10px] font-semibold leading-none tracking-[0.08em] whitespace-nowrap",
        TONE[s.tone]
      )}
    >
      {s.label}
    </span>
  );
}
