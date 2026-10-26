import { apiFetch } from "./client";
import type { FindingKind, FindingLocation, Severity } from "./findings";
import type { ReviewKind, ReviewStatus } from "./vulnerabilities";

// backend/app/schemas/finding_review.py -- the admin queue of requests for a finding to stop
// blocking CI (docs/FINDING_REVIEW.md).
export type FindingReviewItem = {
  vulnerability_id: string;
  project_id: string;
  /** null when the project was deleted since the request: show the id, never link it. */
  project_name: string | null;
  fingerprint: string;
  severity: Severity | null;
  kind_of_finding: FindingKind | null;
  rule_id: string | null;
  rule_name: string | null;
  message: string | null;
  location: FindingLocation | null;
  vulnerability_status: string;
  review: {
    kind: ReviewKind;
    status: ReviewStatus;
    file_path: string;
    requested_by_user_id: string;
    requested_at: string;
    request_comment: string;
    reviewed_by_user_id: string | null;
    reviewed_at: string | null;
    review_comment: string | null;
  };
  requested_by_email: string | null;
  reviewed_by_email: string | null;
};

export type FindingReviewList = { items: FindingReviewItem[]; pending_count: number };

export function listFindingReviews(status: ReviewStatus) {
  return apiFetch<FindingReviewList>(`/admin/finding-reviews?status=${status}`);
}

export function decideFindingReview(vulnerabilityId: string, body: { decision: "accept" | "reject"; comment?: string }) {
  return apiFetch<FindingReviewItem>(`/admin/finding-reviews/${vulnerabilityId}/decide`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function revokeFindingReview(vulnerabilityId: string, comment: string) {
  return apiFetch<FindingReviewItem>(`/admin/finding-reviews/${vulnerabilityId}/revoke`, {
    method: "POST",
    body: JSON.stringify({ comment }),
  });
}
