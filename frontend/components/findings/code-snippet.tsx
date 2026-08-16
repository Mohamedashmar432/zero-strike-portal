import { cn } from "@/lib/utils";

export function CodeSnippet({
  snippet,
  snippetStartLine,
  highlightStart,
  highlightEnd,
}: {
  snippet: string;
  snippetStartLine: number | null;
  highlightStart: number | null;
  highlightEnd: number | null;
}) {
  const lines = snippet.split("\n");
  const startLine = snippetStartLine ?? 1;
  const canHighlight = snippetStartLine != null && highlightStart != null && highlightEnd != null;

  return (
    <div className="overflow-x-auto rounded-lg border border-border/70 bg-[#0d1117] text-[#e6edf3]">
      <table className="w-full border-collapse font-mono text-xs leading-relaxed">
        <tbody>
          {lines.map((line, i) => {
            const lineNumber = startLine + i;
            const isHighlighted = canHighlight && lineNumber >= highlightStart! && lineNumber <= highlightEnd!;
            return (
              <tr key={i} className={cn(isHighlighted && "bg-severity-critical/15")}>
                <td
                  className={cn(
                    "w-px border-l-2 border-transparent px-3 py-0.5 text-right text-[#7d8590] select-none tabular-nums font-mono text-[11px]",
                    isHighlighted && "border-severity-critical text-severity-critical font-bold"
                  )}
                >
                  {lineNumber}
                </td>
                <td className="w-full px-3 py-0.5 whitespace-pre font-mono text-[12px]">{line}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
