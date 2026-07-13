import type { ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export function DataTableCard({
  isLoading,
  isError,
  errorMessage,
  isEmpty,
  emptyState,
  skeletonRows = 3,
  bare = false,
  children,
}: {
  isLoading: boolean;
  isError: boolean;
  errorMessage?: string;
  isEmpty: boolean;
  emptyState: ReactNode;
  skeletonRows?: number;
  /**
   * Skip the Card/CardContent wrapper and render the loading/error/empty/content
   * states directly. For callers whose populated state already brings its own
   * wrapper (e.g. a bare grid of individually-carded items), so they can still
   * reuse this shared state logic without a doubled-up Card.
   */
  bare?: boolean;
  children: ReactNode;
}) {
  const content = isLoading ? (
    <div className="space-y-2 p-4">
      {Array.from({ length: skeletonRows }).map((_, index) => (
        <Skeleton key={index} className="h-8 w-full" />
      ))}
    </div>
  ) : isError ? (
    <p className="p-4 text-sm text-destructive">{errorMessage ?? "Failed to load data."}</p>
  ) : isEmpty ? (
    emptyState
  ) : (
    children
  );

  if (bare) return content;

  return (
    <Card>
      <CardContent className="p-0">{content}</CardContent>
    </Card>
  );
}
