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
  children,
}: {
  isLoading: boolean;
  isError: boolean;
  errorMessage?: string;
  isEmpty: boolean;
  emptyState: ReactNode;
  skeletonRows?: number;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardContent className="p-0">
        {isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: skeletonRows }).map((_, index) => (
              <Skeleton key={index} className="h-8 w-full" />
            ))}
          </div>
        ) : isError ? (
          <p className="p-4 text-center text-sm text-destructive">
            {errorMessage ?? "Failed to load data."}
          </p>
        ) : isEmpty ? (
          emptyState
        ) : (
          children
        )}
      </CardContent>
    </Card>
  );
}
