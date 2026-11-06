// Mirrors backend/app/services/finding_review_service.py: validate_risk_comment. The server stays
// the authority (it answers 422); this exists so the dialog can show a live counter and never
// round-trip the common mistake.
export const MIN_RISK_COMMENT_CHARS = 40;
export const MIN_RISK_COMMENT_WORDS = 6;
const PLACEHOLDERS = new Set(["n/a", "na", "none", "test", "testing", "asdf", "todo", "tbd", "ok", "accepted"]);

/** Words of two or more letters -- digits and underscores never count. */
export function riskCommentWords(text: string): string[] {
  return text.match(/\p{L}{2,}/gu) ?? [];
}

export type RiskCommentCheck = { ok: boolean; chars: number; words: number; message: string | null };

export function checkRiskComment(comment: string | null | undefined): RiskCommentCheck {
  const text = (comment ?? "").trim();
  const words = riskCommentWords(text);
  const distinct = new Set(words.map((w) => w.toLowerCase())).size;
  const base = { chars: text.length, words: words.length };
  if (text === "") return { ...base, ok: false, message: "A comment is required to accept risk." };
  if (PLACEHOLDERS.has(text.toLowerCase()) || distinct < 3) {
    return { ...base, ok: false, message: "Say why the risk is acceptable, not a placeholder." };
  }
  if (text.length < MIN_RISK_COMMENT_CHARS || words.length < MIN_RISK_COMMENT_WORDS) {
    return {
      ...base,
      ok: false,
      message: `Needs at least ${MIN_RISK_COMMENT_CHARS} characters and ${MIN_RISK_COMMENT_WORDS} words explaining why it is acceptable.`,
    };
  }
  return { ...base, ok: true, message: null };
}
