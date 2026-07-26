import { diffLines } from "diff";
import { cn } from "@/lib/utils";

type SplitRow = {
  kind: "same" | "add" | "del";
  left: string | null;
  leftNo: number | null;
  right: string | null;
  rightNo: number | null;
};

type UnifiedRow = {
  kind: "same" | "add" | "del";
  oldNo: number | null;
  newNo: number | null;
  text: string;
};

function splitLines(value: string): string[] {
  const lines = value.split("\n");
  if (lines.length && lines[lines.length - 1] === "") lines.pop(); // drop empty tail from a final newline
  return lines;
}

function buildSplitRows(original: string, patched: string): SplitRow[] {
  const rows: SplitRow[] = [];
  let ln = 1;
  let rn = 1;
  for (const part of diffLines(original, patched)) {
    for (const line of splitLines(part.value)) {
      if (part.added) rows.push({ kind: "add", left: null, leftNo: null, right: line, rightNo: rn++ });
      else if (part.removed) rows.push({ kind: "del", left: line, leftNo: ln++, right: null, rightNo: null });
      else rows.push({ kind: "same", left: line, leftNo: ln++, right: line, rightNo: rn++ });
    }
  }
  return rows;
}

function buildUnifiedRows(original: string, patched: string): UnifiedRow[] {
  const rows: UnifiedRow[] = [];
  let oldNo = 1;
  let newNo = 1;
  for (const part of diffLines(original, patched)) {
    for (const line of splitLines(part.value)) {
      if (part.added) rows.push({ kind: "add", oldNo: null, newNo: newNo++, text: line });
      else if (part.removed) rows.push({ kind: "del", oldNo: oldNo++, newNo: null, text: line });
      else rows.push({ kind: "same", oldNo: oldNo++, newNo: newNo++, text: line });
    }
  }
  return rows;
}

function Cell({ no, text, tone }: { no: number | null; text: string | null; tone: "same" | "add" | "del" | "empty" }) {
  const bg = tone === "add" ? "bg-emerald-500/10" : tone === "del" ? "bg-severity-critical/15" : "";
  const sign = tone === "add" ? "+" : tone === "del" ? "-" : " ";
  return (
    <>
      <td className={cn("w-px px-2 py-0.5 text-right text-[#8a827d] select-none tabular-nums", bg)}>{no ?? ""}</td>
      <td className={cn("w-1/2 px-3 py-0.5 whitespace-pre", bg)}>
        {text !== null ? <span className="text-[#8a827d] select-none">{sign} </span> : null}
        {text}
      </td>
    </>
  );
}

function DiffHeader({ filePath }: { filePath: string }) {
  return (
    <div className="border-b border-white/10 px-3 py-1.5 font-mono text-xs text-[#8a827d]">{filePath}</div>
  );
}

/**
 * GitHub-style code diff: red rows are the vulnerable lines, green rows the AI-recommended fix.
 * `mode="unified"` (default) is the single-column GitHub PR look; `mode="split"` keeps the
 * side-by-side view. Computed client-side with jsdiff; palette mirrors findings/code-snippet.tsx.
 */
export function DiffView({
  original,
  patched,
  mode = "unified",
  filePath,
}: {
  original: string;
  patched: string;
  mode?: "unified" | "split";
  filePath?: string | null;
}) {
  return (
    <div className="overflow-x-auto rounded-lg bg-[#1e1c1b] text-[#d4ccc8]">
      {filePath ? <DiffHeader filePath={filePath} /> : null}
      {mode === "split" ? (
        <table className="w-full border-collapse font-mono text-xs leading-relaxed">
          <tbody>
            {buildSplitRows(original, patched).map((r, i) => (
              <tr key={i}>
                <Cell no={r.leftNo} text={r.left} tone={r.left === null ? "empty" : r.kind === "del" ? "del" : "same"} />
                <Cell
                  no={r.rightNo}
                  text={r.right}
                  tone={r.right === null ? "empty" : r.kind === "add" ? "add" : "same"}
                />
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <table className="w-full border-collapse font-mono text-xs leading-relaxed">
          <tbody>
            {buildUnifiedRows(original, patched).map((r, i) => {
              const bg = r.kind === "add" ? "bg-emerald-500/10" : r.kind === "del" ? "bg-severity-critical/15" : "";
              const sign = r.kind === "add" ? "+" : r.kind === "del" ? "-" : " ";
              return (
                <tr key={i}>
                  <td className={cn("w-px px-2 py-0.5 text-right text-[#8a827d] select-none tabular-nums", bg)}>
                    {r.oldNo ?? ""}
                  </td>
                  <td className={cn("w-px px-2 py-0.5 text-right text-[#8a827d] select-none tabular-nums", bg)}>
                    {r.newNo ?? ""}
                  </td>
                  <td className={cn("px-3 py-0.5 whitespace-pre", bg)}>
                    <span className="text-[#8a827d] select-none">{sign} </span>
                    {r.text}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
