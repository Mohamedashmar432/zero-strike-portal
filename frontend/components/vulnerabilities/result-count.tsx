/** Announces the result total to assistive tech whenever filters change (polite live region). */
export function ResultCount({
  total,
  isLoading,
  noun = "findings",
  filterCount = 0,
}: {
  total: number | undefined;
  isLoading?: boolean;
  noun?: string;
  filterCount?: number;
}) {
  const text = isLoading
    ? "Loading results"
    : total === undefined
      ? ""
      : `${total.toLocaleString()} ${total === 1 ? noun.replace(/s$/, "") : noun}${
          filterCount > 0 ? ` · ${filterCount} filter${filterCount === 1 ? "" : "s"} active` : ""
        }`;
  return (
    <p role="status" aria-live="polite" aria-atomic="true" className="legend text-muted-foreground">
      {text}
    </p>
  );
}
