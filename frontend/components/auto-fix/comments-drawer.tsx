"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CornerUpRight, MessageSquare, Send } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { addFindingComment, listFindingComments, type AiFixProposal } from "@/lib/api/auto-fix";
import { ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";

function CommentThread({ findingId, scanId }: { findingId: string; scanId: string }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const key = queryKeys.ai.autofix.comments(findingId);
  const { data, isLoading } = useQuery({ queryKey: key, queryFn: () => listFindingComments(findingId) });

  const add = useMutation({
    mutationFn: (body: string) => addFindingComment(findingId, { body }),
    onSuccess: () => {
      setText("");
      qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: queryKeys.ai.autofix.commentSummary(scanId) });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed to add comment"),
  });

  const items = data?.items ?? [];
  const submit = () => {
    const b = text.trim();
    if (b) add.mutate(b);
  };

  return (
    <div className="space-y-3">
      {isLoading ? (
        <Skeleton className="h-12 w-full" />
      ) : items.length ? (
        items.map((c) => (
          <div key={c.id} className="rounded-md bg-muted/40 px-3 py-2 text-sm">
            <div className="mb-0.5 flex items-baseline gap-2">
              <span className="font-medium">{c.author_name || c.author_email || "Someone"}</span>
              <span className="text-xs text-muted-foreground">{new Date(c.created_at).toLocaleString()}</span>
            </div>
            <p className="whitespace-pre-wrap">{c.body}</p>
          </div>
        ))
      ) : (
        <p className="text-sm text-muted-foreground">No comments yet. Start the discussion below.</p>
      )}
      <div className="flex items-center gap-2">
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Add a comment for your team…"
          disabled={add.isPending}
          className="h-9"
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              submit();
            }
          }}
        />
        <Button size="icon-sm" onClick={submit} disabled={add.isPending || !text.trim()} title="Comment">
          <Send />
        </Button>
      </div>
    </div>
  );
}

function FindingCommentBlock({
  proposal,
  scanId,
  count,
  onJump,
}: {
  proposal: AiFixProposal;
  scanId: string;
  count: number;
  onJump: (findingId: string) => void;
}) {
  return (
    <div className="rounded-lg border">
      <div className="flex items-center gap-2 border-b px-3 py-2">
        {proposal.finding_severity && <SeverityBadge severity={proposal.finding_severity} />}
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{proposal.finding_rule_name ?? "Finding"}</span>
        {count > 0 && (
          <span className="shrink-0 rounded-full bg-brand/15 px-1.5 text-xs text-brand tabular-nums">{count}</span>
        )}
        <Button size="icon-sm" variant="ghost" title="Jump to this finding" onClick={() => onJump(proposal.finding_id)}>
          <CornerUpRight />
        </Button>
      </div>
      <div className="px-3 py-3">
        <CommentThread findingId={proposal.finding_id} scanId={scanId} />
      </div>
    </div>
  );
}

/** Right-side floating panel for team comments. Non-modal: the page behind stays visible and
 * interactive (no dimming/blur backdrop). Two modes:
 *  - a single finding (opened from that finding's comment button) → only that finding's thread;
 *  - "view all" (selectedId null) → only findings that actually have comments, each with its thread. */
export function CommentsDrawer({
  open,
  onOpenChange,
  scanId,
  proposals,
  commentCounts,
  selectedId,
  onJump,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  scanId: string;
  proposals: AiFixProposal[];
  commentCounts: Map<string, number>;
  selectedId: string | null;
  onJump: (findingId: string) => void;
}) {
  const single = selectedId ? proposals.find((p) => p.finding_id === selectedId) ?? null : null;
  // "View all" mode: only findings that have comments, most-commented first.
  const commented = [...proposals]
    .filter((p) => (commentCounts.get(p.finding_id) ?? 0) > 0)
    .sort((a, b) => (commentCounts.get(b.finding_id) ?? 0) - (commentCounts.get(a.finding_id) ?? 0));

  return (
    <Sheet open={open} onOpenChange={onOpenChange} modal={false} disablePointerDismissal>
      <SheetContent side="right" showOverlay={false} className="w-full gap-0 sm:max-w-md">
        <SheetHeader className="border-b">
          <SheetTitle className="flex items-center gap-2">
            <MessageSquare className="size-4" /> {single ? "Comments on this finding" : "Comments"}
          </SheetTitle>
          <SheetDescription>
            {single
              ? single.finding_rule_name ?? "Discuss this finding with your team."
              : "Findings your team has commented on. Jump to any finding to review it in context."}
          </SheetDescription>
        </SheetHeader>
        <div className="flex-1 space-y-2 overflow-y-auto p-3">
          {single ? (
            <FindingCommentBlock
              proposal={single}
              scanId={scanId}
              count={commentCounts.get(single.finding_id) ?? 0}
              onJump={onJump}
            />
          ) : commented.length ? (
            commented.map((p) => (
              <FindingCommentBlock
                key={p.finding_id}
                proposal={p}
                scanId={scanId}
                count={commentCounts.get(p.finding_id) ?? 0}
                onJump={onJump}
              />
            ))
          ) : (
            <p className="px-1 py-8 text-center text-sm text-muted-foreground">
              No comments yet. Open a finding and use its Comments button to start a discussion.
            </p>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
