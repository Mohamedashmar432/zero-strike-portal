"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Send, Sparkles, Wand2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { askFixProposal, getFixConversation, reviseFixProposal } from "@/lib/api/auto-fix";
import { ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { cn } from "@/lib/utils";

/** Ask-AI panel for one proposed fix. "Ask" is read-only Q&A over the exact code context; "Apply as
 * change" re-runs the fix agent with the instruction and refreshes the proposal. Rendered only when
 * its card is expanded, so the conversation query stays lazy. */
export function FixChat({
  proposalId,
  canRevise,
  invalidateKey,
}: {
  proposalId: string;
  canRevise: boolean;
  invalidateKey: readonly unknown[];
}) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const key = queryKeys.ai.autofix.conversation(proposalId);
  const scrollRef = useRef<HTMLDivElement>(null);

  const { data } = useQuery({ queryKey: key, queryFn: () => getFixConversation(proposalId) });

  const onError = (err: unknown) =>
    toast.error(err instanceof ApiError ? err.message : "Something went wrong");

  const ask = useMutation({
    mutationFn: (question: string) => askFixProposal(proposalId, { question }),
    onSuccess: (conv) => {
      qc.setQueryData(key, conv);
      setText("");
    },
    onError,
  });

  const revise = useMutation({
    mutationFn: (instruction: string) => reviseFixProposal(proposalId, { instruction }),
    onSuccess: () => {
      toast.success("Regenerating the fix with your change…");
      setText("");
      qc.invalidateQueries({ queryKey: invalidateKey });
      qc.invalidateQueries({ queryKey: key });
    },
    onError,
  });

  const messages = data?.messages ?? [];
  const busy = ask.isPending || revise.isPending;

  // Keep the newest message in view.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages.length, busy]);

  const submitAsk = () => {
    const q = text.trim();
    if (q) ask.mutate(q);
  };

  return (
    <div className="overflow-hidden rounded-lg border bg-muted/30">
      <div className="flex items-center gap-2 border-b bg-muted/40 px-3 py-2">
        <Sparkles className="size-4 text-brand" />
        <span className="text-sm font-medium">Ask AI about this fix</span>
        <span className="ml-auto text-xs text-muted-foreground">Answers use this finding&apos;s code context</span>
      </div>

      {(messages.length > 0 || busy) && (
        <div ref={scrollRef} className="max-h-72 space-y-3 overflow-y-auto p-3">
          {messages.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="flex justify-end">
                <div
                  className={cn(
                    "max-w-[85%] rounded-2xl rounded-br-sm px-3 py-2 text-sm",
                    m.kind === "revision"
                      ? "border border-severity-medium/40 bg-severity-medium/10"
                      : "bg-brand/10"
                  )}
                >
                  {m.kind === "revision" && (
                    <span className="mb-0.5 flex items-center gap-1 text-xs font-medium text-severity-medium">
                      <Wand2 className="size-3" /> Change requested
                    </span>
                  )}
                  <span className="whitespace-pre-wrap">{m.body}</span>
                </div>
              </div>
            ) : (
              <div key={i} className="flex items-start gap-2">
                <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-brand/15">
                  <Sparkles className="size-3.5 text-brand" />
                </span>
                <div className="max-w-[85%] rounded-2xl rounded-bl-sm bg-background px-3 py-2 text-sm whitespace-pre-wrap">
                  {m.body}
                </div>
              </div>
            )
          )}
          {busy && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className="flex size-6 items-center justify-center rounded-full bg-brand/15">
                <Sparkles className="size-3.5 text-brand" />
              </span>
              <Loader2 className="size-3.5 animate-spin" />
              {revise.isPending ? "Regenerating the fix…" : "Thinking…"}
            </div>
          )}
        </div>
      )}

      <div className="flex items-center gap-2 border-t p-2">
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Ask a question, or describe a change…"
          disabled={busy}
          className="h-9 border-0 bg-transparent shadow-none focus-visible:ring-0"
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              submitAsk();
            }
          }}
        />
        {canRevise && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => text.trim() && revise.mutate(text.trim())}
            disabled={busy || !text.trim()}
            title="Re-generate the fix using your instruction"
          >
            <Wand2 /> Apply as change
          </Button>
        )}
        <Button size="icon-sm" onClick={submitAsk} disabled={busy || !text.trim()} title="Ask">
          <Send />
        </Button>
      </div>
    </div>
  );
}
