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
  // snippetStartLine is the real file line number of the snippet's first line — when
  // absent (offset unknown) fall back to plain numbering from 1 with no highlight,
  // rather than guessing which line is the vulnerable one.
  const startLine = snippetStartLine ?? 1;
  const canHighlight = snippetStartLine != null && highlightStart != null && highlightEnd != null;

  return (
    <div className="overflow-x-auto rounded-lg bg-[#1e1c1b] text-[#d4ccc8]">
      <table className="w-full border-collapse font-mono text-xs leading-relaxed">
        <tbody>
          {lines.map((line, i) => {
            const lineNumber = startLine + i;
            const isHighlighted = canHighlight && lineNumber >= highlightStart! && lineNumber <= highlightEnd!;
            return (
              <tr key={i} className={cn(isHighlighted && "bg-severity-critical/15")}>
                <td
                  className={cn(
                    "w-px border-l-2 border-transparent px-3 py-0.5 text-right text-[#8a827d] select-none tabular-nums",
                    isHighlighted && "border-severity-critical text-severity-critical"
                  )}
                >
                  {lineNumber}
                </td>
                <td className="w-full px-3 py-0.5 whitespace-pre">{line}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
