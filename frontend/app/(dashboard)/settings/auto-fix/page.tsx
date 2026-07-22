"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ShieldCheck, Wand2, XCircle } from "lucide-react";
import Link from "next/link";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getAiStatus } from "@/lib/api/ai";
import { queryKeys } from "@/lib/api/query-keys";

export default function AutoFixSettingsPage() {
  const { data: aiStatus } = useQuery({ queryKey: queryKeys.ai.status(), queryFn: getAiStatus });
  const enabled = aiStatus?.enabled ?? false;

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Auto-Fix</h2>
        <p className="text-sm text-muted-foreground">
          AI-generated, human-approved remediation for findings — reviewable diffs and one-click pull
          requests.
        </p>
      </div>

      <Alert className={enabled ? "border-emerald-500/50 bg-emerald-500/5" : undefined}>
        {enabled ? <CheckCircle2 className="text-emerald-500" /> : <XCircle />}
        <AlertTitle>{enabled ? "AI is configured" : "AI provider not configured"}</AlertTitle>
        <AlertDescription>
          Auto-Fix needs an active, tool-capable AI provider (e.g. Anthropic or OpenAI).{" "}
          <Link href="/settings/ai-provider" className="underline underline-offset-4">
            Configure an AI provider
          </Link>
          . Local providers (LM Studio) can’t drive the fix agent.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Wand2 className="size-4" /> How it works
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>
            Open a completed scan and click <strong>Auto AI Fix</strong> (or <strong>Generate Fix</strong> on a
            single finding). Proposals appear on the project’s <strong>Auto-Fix</strong> tab with a confidence
            score and a side-by-side diff.
          </p>
          <p>
            Only proposals with high confidence surface as actionable; the rest are flagged for manual review
            with a reason.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="size-4" /> Safety
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>The agent is read-only and never sees a repository token — it only proposes a patch.</p>
          <p>
            A pull request is opened only after an <strong>owner or admin</strong> explicitly approves, and only
            after the patch is re-scanned to confirm it clears the finding without introducing new ones.
            Nothing is auto-committed and nothing is auto-merged.
          </p>
          <p>Azure DevOps connections must be reconnected to grant write access before a PR can be opened.</p>
        </CardContent>
      </Card>
    </div>
  );
}
