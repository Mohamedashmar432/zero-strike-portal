import { describe, expect, test } from "vitest";
import {
  cardPreview,
  deliveryChips,
  effectivePolicyText,
  formatBytes,
  lagLabel,
  projectSeverityOptions,
} from "./live-alerts";

describe("projectSeverityOptions", () => {
  const disabled = (ws: Parameters<typeof projectSeverityOptions>[0]) =>
    projectSeverityOptions(ws).filter((o) => o.disabled).map((o) => o.value);

  test("workspace medium allows everything", () => expect(disabled("medium")).toEqual([]));
  test("workspace high disables medium only", () => expect(disabled("high")).toEqual(["medium"]));
  test("workspace critical disables high and medium", () =>
    expect(disabled("critical")).toEqual(["high", "medium"]));
  test("off and inherit are never disabled", () => {
    const opts = projectSeverityOptions("critical");
    expect(opts.find((o) => o.value === "off")?.disabled).toBe(false);
    expect(opts[0]).toMatchObject({ value: "inherit", label: "Inherit (workspace: Critical only)" });
  });
});

describe("deliveryChips", () => {
  test("only a recorded sent outcome reads as sent", () => {
    const chips = deliveryChips({ channels: 2, in_app: 1, project_webhook: "failed", project_email: "not_configured" });
    expect(chips.map((c) => c.label)).toEqual([
      "Project webhook: failed",
      "Email: not configured",
      "2 channels matched",
      "1 in-app notice",
    ]);
    expect(chips.filter((c) => /sent/i.test(c.label))).toEqual([]);
    expect(chips[0].tone).toBe("bad");
  });
  test("sent is ok", () => {
    const [w, e] = deliveryChips({ channels: 0, in_app: 0, project_webhook: "sent", project_email: "sent" });
    expect([w.tone, e.tone]).toEqual(["ok", "ok"]);
  });
});

describe("lagLabel", () => {
  test.each([
    [null, "—"],
    [12, "12 min"],
    [60, "1 h"],
    [185, "3 h 5 min"],
    [1500, "1 d 1 h"],
    [2880, "2 d"],
  ])("%s", (m, out) => expect(lagLabel(m)).toBe(out));
});

describe("cardPreview", () => {
  test("reads title, text and facts", () => {
    const card = {
      body: [
        {
          type: "Container",
          items: [
            { type: "TextBlock", text: "THINKSHIELD" },
            { type: "TextBlock", text: "New advisory for demo-app" },
          ],
        },
        { type: "TextBlock", text: "Details" },
        { type: "Container", items: [{ type: "FactSet", facts: [{ title: "Package", value: "pkg@1.0.0" }] }] },
      ],
    };
    expect(cardPreview(card)).toEqual({
      title: "New advisory for demo-app",
      text: "Details",
      facts: [{ title: "Package", value: "pkg@1.0.0" }],
    });
  });
  test("tolerates an unknown shape", () => expect(cardPreview({})).toEqual({ title: "", text: null, facts: [] }));
});

test("formatBytes", () => {
  expect(formatBytes(900)).toBe("900 B");
  expect(formatBytes(2048)).toBe("2.0 KB");
});

test("effectivePolicyText", () => {
  expect(effectivePolicyText({ enabled: false, effective_min_severity: "high" })).toBe("Disabled by the workspace");
  expect(effectivePolicyText({ enabled: true, effective_min_severity: "off" })).toBe("Off for this project");
  expect(effectivePolicyText({ enabled: true, effective_min_severity: "high" })).toBe("Alerting on High and above");
});
