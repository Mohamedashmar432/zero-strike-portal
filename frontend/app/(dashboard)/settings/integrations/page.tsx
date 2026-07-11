"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import { connectProvider, disconnectProvider, listConnections, type Provider } from "@/lib/api/connections";

const PROVIDERS: { value: Provider; label: string }[] = [
  { value: "github", label: "GitHub" },
  { value: "azure_devops", label: "Azure DevOps" },
];

export default function IntegrationsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { data: connections, isLoading } = useQuery({
    queryKey: ["connections"],
    queryFn: listConnections,
  });

  useEffect(() => {
    const connected = searchParams.get("connected");
    const error = searchParams.get("error");
    if (connected) {
      toast.success(`Connected to ${connected === "azure_devops" ? "Azure DevOps" : "GitHub"}`);
      queryClient.invalidateQueries({ queryKey: ["connections"] });
    } else if (error) {
      toast.error("Failed to connect — please try again");
    }
    if (connected || error) router.replace("/settings/integrations");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const connect = useMutation({
    mutationFn: connectProvider,
    onSuccess: ({ authorize_url }) => {
      window.location.href = authorize_url;
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to start connection"),
  });

  const disconnect = useMutation({
    mutationFn: disconnectProvider,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      toast.success("Disconnected");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to disconnect"),
  });

  return (
    <div className="max-w-md space-y-6">
      <h1 className="text-xl font-semibold">Integrations</h1>
      <p className="text-sm text-muted-foreground">
        Connect GitHub or Azure DevOps to import a repo directly when starting a cloud scan, instead of
        pasting a URL and access token.
      </p>
      <div className="space-y-4">
        {isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          PROVIDERS.map((p) => {
            const conn = connections?.find((c) => c.provider === p.value);
            return (
              <Card key={p.value}>
                <CardHeader>
                  <CardTitle className="flex items-center justify-between text-base">
                    {p.label}
                    {conn && (
                      <Badge variant="secondary" className="font-mono">
                        {conn.account_login}
                      </Badge>
                    )}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {conn ? (
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => disconnect.mutate(p.value)}
                      disabled={disconnect.isPending}
                    >
                      Disconnect
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => connect.mutate(p.value)}
                      disabled={connect.isPending}
                    >
                      Connect {p.label}
                    </Button>
                  )}
                </CardContent>
              </Card>
            );
          })
        )}
      </div>
    </div>
  );
}
