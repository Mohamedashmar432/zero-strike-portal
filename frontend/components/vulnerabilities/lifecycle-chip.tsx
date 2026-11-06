import type { AckState } from "@/lib/api/risk-acknowledgements";
import { cn } from "@/lib/utils";
import { TONE_CLASS, lifecycleOf, type LifecycleInput } from "@/lib/vulnerability-lifecycle";

/**
 * The finding's state as one chip, with review micro-tags beside it (PENDING REVIEW, EXEMPT · FP,
 * EXEMPT · RISK, ACK PENDING, ACKNOWLEDGED). Same left-edge-tag shape as the other status badges;
 * the text is always rendered, so colour is never the only signal.
 */
export function LifecycleChip({ finding, ack = null }: { finding: LifecycleInput; ack?: AckState | null }) {
  const l = lifecycleOf(finding, ack);
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <span
        className={cn(
          "inline-flex items-center rounded-sm border-l-2 px-1.5 py-0.5 font-mono text-[11px] font-semibold leading-none tracking-[0.08em]",
          TONE_CLASS[l.tone]
        )}
      >
        {l.label}
      </span>
      {l.tags.map((t) => (
        <span
          key={t.label}
          title={t.title}
          className={cn(
            "inline-flex items-center rounded-sm border-l-2 px-1.5 py-0.5 font-mono text-[10px] font-semibold leading-none tracking-[0.08em]",
            TONE_CLASS[t.tone]
          )}
        >
          {t.label}
        </span>
      ))}
    </span>
  );
}
