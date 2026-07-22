import { render } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { DiffView } from "./diff-view";

describe("DiffView", () => {
  test("renders removed and added lines with +/- markers", () => {
    const { container } = render(<DiffView original={"a\nold\nc"} patched={"a\nnew\nc"} />);
    const text = container.textContent ?? "";
    // unchanged lines appear on both sides; the changed line shows as - old / + new.
    expect(text).toContain("old");
    expect(text).toContain("new");
    expect(text).toContain("- ");
    expect(text).toContain("+ ");
  });

  test("identical input produces only context rows (no markers)", () => {
    const { container } = render(<DiffView original={"x\ny"} patched={"x\ny"} />);
    const text = container.textContent ?? "";
    expect(text).not.toContain("+ ");
    expect(text).not.toContain("- ");
  });
});
