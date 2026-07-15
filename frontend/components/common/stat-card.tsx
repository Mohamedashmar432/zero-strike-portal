import type { ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export function StatCard({
  label,
  value,
  caption,
  valueClassName,
  pillClassName,
  size = "lg",
  isLoading,
}: {
  label: string;
  value: ReactNode;
  caption?: string;
  valueClassName?: string;
  pillClassName?: string;
  size?: "sm" | "lg";
  isLoading?: boolean;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent className={cn(caption && "space-y-1.5")}>
        {isLoading ? (
          <Skeleton className="h-9 w-12" />
        ) : (
          <span
            className={cn(
              "block font-semibold tracking-tight",
              size === "lg" ? "text-3xl" : "text-2xl",
              valueClassName
            )}
          >
            {value}
          </span>
        )}
        {caption &&
          (pillClassName ? (
            <span className={cn("inline-block rounded-sm px-2 py-0.5 text-xs font-medium", pillClassName)}>
              {caption}
            </span>
          ) : (
            <p className="text-xs text-muted-foreground">{caption}</p>
          ))}
      </CardContent>
    </Card>
  );
}
