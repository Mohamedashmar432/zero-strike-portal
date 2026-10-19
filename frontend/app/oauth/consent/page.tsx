"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { OctagonAlert } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, retryUnlessForbiddenOrMissing } from "@/lib/api/client";
import { decideConsent, getConsentRequest } from "@/lib/api/oauth";
import { queryKeys } from "@/lib/api/query-keys";
import { useAuth } from "@/providers/auth-provider";

const SCOPE_LABELS: Record<string, string> = {
  "mcp:read": "Read your projects, scans, findings, compliance audits and fix proposals. It cannot change anything.",
};

function ConsentForm() {
  const { user, isAuthenticating, isRestoringSession } = useAuth();
  const router = useRouter();
  const requestId = useSearchParams().get("request");

  // Signed out: log in, then come back to this exact URL (the request id rides along in `next`).
  useEffect(() => {
    if (isAuthenticating || isRestoringSession || user) return;
    const here = `/oauth/consent?request=${encodeURIComponent(requestId ?? "")}`;
    router.replace(`/login?next=${encodeURIComponent(here)}`);
  }, [user, isAuthenticating, isRestoringSession, requestId, router]);

  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.oauth.consentRequest(requestId ?? ""),
    queryFn: () => getConsentRequest(requestId as string),
    enabled: !!user && !!requestId,
    retry: retryUnlessForbiddenOrMissing,
  });

  const decide = useMutation({
    mutationFn: (decision: "approve" | "deny") => decideConsent(requestId as string, decision),
    // The server hands back the client's own redirect_uri (with the code or the denial attached).
    onSuccess: ({ redirect_to }) => window.location.assign(redirect_to),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not record your decision"),
  });

  if (!user) return null;

  if (!requestId || isError) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">This request cannot be used</CardTitle>
          <CardDescription className="text-[13px]">
            The authorization link has expired or was already used. Start the connection again from your AI client.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (isLoading || !data) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Connect an AI client to thinkShield</CardTitle>
        <CardDescription className="text-[13px]">Review this before you approve it.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <dl className="space-y-3 text-[13px]">
          <div>
            <dt className="legend text-muted-foreground">Application name</dt>
            <dd className="mt-1 break-words text-foreground">{data.client_name}</dd>
          </div>
          <div>
            <dt className="legend text-muted-foreground">Access code will be sent to</dt>
            <dd className="mt-1 break-all font-mono text-base font-bold text-foreground">{data.redirect_host}</dd>
          </div>
          <div>
            <dt className="legend text-muted-foreground">It will be able to</dt>
            <dd className="mt-1 space-y-1 text-foreground">
              {data.scopes.map((s) => (
                <p key={s}>
                  <span className="font-mono text-[11px] text-muted-foreground">{s}</span>
                  <br />
                  {SCOPE_LABELS[s] ?? "Unrecognised scope."}
                </p>
              ))}
            </dd>
          </div>
          <div>
            <dt className="legend text-muted-foreground">Signed in as</dt>
            <dd className="mt-1 text-foreground">{data.account_email}</dd>
          </div>
        </dl>

        <div className="flex items-start gap-2 rounded-sm border-l-2 border-severity-medium bg-severity-medium-tint px-2.5 py-2">
          <OctagonAlert className="mt-px size-3.5 shrink-0 text-severity-medium" aria-hidden="true" />
          <p className="font-mono text-[11px] leading-relaxed text-severity-medium">
            The application name is chosen by whoever registered it and is not verified. Approve only if you started
            this connection and recognise <strong>{data.redirect_host}</strong>.
          </p>
        </div>

        <div className="flex gap-3">
          <Button className="flex-1" disabled={decide.isPending} onClick={() => decide.mutate("approve")}>
            Approve
          </Button>
          <Button
            className="flex-1"
            variant="outline"
            disabled={decide.isPending}
            onClick={() => decide.mutate("deny")}
          >
            Deny
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export default function OAuthConsentPage() {
  return (
    <Suspense fallback={null}>
      <ConsentForm />
    </Suspense>
  );
}
