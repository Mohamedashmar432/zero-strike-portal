import { diffLines } from "diff";
import { cn } from "@/lib/utils";

type Row = {
  kind: "same" | "add" | "del";
  left: string | null;
  leftNo: number | null;
  right: string | null;
  rightNo: number | null;
};

function buildRows(original: string, patched: string): Row[] {
  const rows: Row[] = [];
  let ln = 1;
  let rn = 1;
  for (const part of diffLines(original, patched)) {
    const lines = part.value.split("\n");
    if (lines.length && lines[lines.length - 1] === "") lines.pop(); // drop the empty tail from a final newline
    for (const line of lines) {
      if (part.added) rows.push({ kind: "add", left: null, leftNo: null, right: line, rightNo: rn++ });
      else if (part.removed) rows.push({ kind: "del", left: line, leftNo: ln++, right: null, rightNo: null });
      else rows.push({ kind: "same", left: line, leftNo: ln++, right: line, rightNo: rn++ });
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

/** Side-by-side diff of the original vs patched code, computed client-side with jsdiff. Styling
 * mirrors components/findings/code-snippet.tsx (dark terminal palette). */
export function DiffView({ original, patched }: { original: string; patched: string }) {
  const rows = buildRows(original, patched);
  return (
    <div className="overflow-x-auto rounded-lg bg-[#1e1c1b] text-[#d4ccc8]">
      <table className="w-full border-collapse font-mono text-xs leading-relaxed">
        <tbody>
          {rows.map((r, i) => (
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
    </div>
  );
}
