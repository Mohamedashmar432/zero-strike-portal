import type { LiveAlertDelivery, ProjectLiveAlerts } from "@/lib/api/live-alerts";

export type PolicyValue = "critical" | "high" | "medium" | "off";

export const POLICY_LABEL: Record<PolicyValue, string> = {
  critical: "Critical only",
  high: "High and above",
  medium: "Medium and above",
  off: "Off",
};

// Higher = stricter. "off" is the strictest: it alerts on nothing.
const STRICTNESS: Record<PolicyValue, number> = { medium: 1, high: 2, critical: 3, off: 4 };

export interface SeverityOption {
  value: "inherit" | PolicyValue;
  label: string;
  disabled: boolean;
}

/** A project may only tighten the workspace minimum, so any option looser than it is disabled. */
export function projectSeverityOptions(workspace: PolicyValue): SeverityOption[] {
  const inherit: SeverityOption = {
    value: "inherit",
    label: `Inherit (workspace: ${POLICY_LABEL[workspace]})`,
    disabled: false,
  };
  const rest = (["critical", "high", "medium", "off"] as const).map((value) => ({
    value,
    label: POLICY_LABEL[value],
    disabled: STRICTNESS[value] < STRICTNESS[workspace],
  }));
  return [inherit, ...rest];
}

export type ChipTone = "ok" | "bad" | "muted";
export interface DeliveryChip {
  label: string;
  tone: ChipTone;
}

/** One chip per recorded outcome. Only an outcome of "sent" reads as sent; channel and in-app counts
 * are what the event matched and wrote, not delivery confirmations. */
export function deliveryChips(d: LiveAlertDelivery): DeliveryChip[] {
  const webhook: Record<LiveAlertDelivery["project_webhook"], DeliveryChip> = {
    sent: { label: "Project webhook: sent", tone: "ok" },
    failed: { label: "Project webhook: failed", tone: "bad" },
    off: { label: "Project webhook: off", tone: "muted" },
  };
  const email: Record<LiveAlertDelivery["project_email"], DeliveryChip> = {
    sent: { label: "Email: sent", tone: "ok" },
    failed: { label: "Email: failed", tone: "bad" },
    not_configured: { label: "Email: not configured", tone: "muted" },
    off: { label: "Email: off", tone: "muted" },
  };
  const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  return [
    webhook[d.project_webhook],
    email[d.project_email],
    { label: plural(d.channels, "channel matched", "channels matched"), tone: "muted" },
    { label: plural(d.in_app, "in-app notice", "in-app notices"), tone: "muted" },
  ];
}

/** Feed lag in minutes as "12 min" / "3 h 5 min" / "2 d 4 h". */
export function lagLabel(minutes: number | null): string {
  if (minutes === null) return "—";
  const m = Math.max(0, Math.round(minutes));
  if (m < 60) return `${m} min`;
  if (m < 1440) return m % 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m / 60} h`;
  const h = Math.floor((m % 1440) / 60);
  return h ? `${Math.floor(m / 1440)} d ${h} h` : `${Math.floor(m / 1440)} d`;
}

export interface CardPreview {
  title: string;
  text: string | null;
  facts: { title: string; value: string }[];
}

interface CardNode {
  type?: string;
  text?: string;
  items?: CardNode[];
  facts?: { title: string; value: string }[];
}

/** Reads the title, message and fact lines out of the Adaptive Card the backend built
 * (header container, optional text block, fact set). Unknown shapes yield empty fields. */
export function cardPreview(card: Record<string, unknown>): CardPreview {
  const body = (Array.isArray(card.body) ? card.body : []) as CardNode[];
  const header = body.find((n) => n.type === "Container" && n.items?.some((i) => i.type === "TextBlock"));
  const headerTexts = (header?.items ?? []).filter((i) => i.type === "TextBlock");
  const title = headerTexts[1]?.text ?? headerTexts[0]?.text ?? "";
  const text = body.find((n) => n.type === "TextBlock")?.text ?? null;
  const facts: CardPreview["facts"] = [];
  for (const n of body) {
    for (const i of n.items ?? []) if (i.type === "FactSet") facts.push(...(i.facts ?? []));
  }
  return { title, text, facts };
}

export function formatBytes(n: number): string {
  return n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} KB`;
}

/** The project's effective policy in words. */
export function effectivePolicyText(p: Pick<ProjectLiveAlerts, "enabled" | "effective_min_severity">): string {
  if (!p.enabled) return "Disabled by the workspace";
  if (p.effective_min_severity === "off") return "Off for this project";
  return `Alerting on ${POLICY_LABEL[p.effective_min_severity]}`;
}
