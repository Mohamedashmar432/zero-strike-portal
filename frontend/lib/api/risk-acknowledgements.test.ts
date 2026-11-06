import { afterEach, describe, expect, test, vi } from "vitest";
import { ApiError } from "./client";
import { filterByKind, type FindingReviewItem } from "./finding-reviews";
import {
  MAX_EXTRA_RECIPIENTS,
  acknowledgeByToken,
  addRecipients,
  deliverySummary,
  isValidEmail,
  lookupAckToken,
  recipientCount,
  tokenFromHash,
} from "./risk-acknowledgements";

describe("recipient chips", () => {
  test("validates addresses", () => {
    expect(isValidEmail("a@b.co")).toBe(true);
    expect(isValidEmail("not-an-email")).toBe(false);
    expect(isValidEmail("a@b")).toBe(false);
  });

  test("splits pasted lists, dedupes and reports invalid entries", () => {
    const r = addRecipients(["a@x.com"], "B@x.com, a@x.com; nope  c@x.com");
    expect(r.next).toEqual(["a@x.com", "b@x.com", "c@x.com"]);
    expect(r.invalid).toEqual(["nope"]);
    expect(r.overflow).toBe(0);
  });

  test("caps at the extra-recipient limit", () => {
    const many = Array.from({ length: MAX_EXTRA_RECIPIENTS + 2 }, (_, i) => `u${i}@x.com`).join(" ");
    const r = addRecipients([], many);
    expect(r.next).toHaveLength(MAX_EXTRA_RECIPIENTS);
    expect(r.overflow).toBe(2);
  });

  test("the owner is always counted", () => {
    expect(recipientCount([])).toBe(1);
    expect(recipientCount(["a@x.com", "b@x.com"])).toBe(3);
  });
});

describe("deliverySummary says sent only when a recipient delivery is sent", () => {
  test("all sent", () => {
    expect(deliverySummary([{ delivery: "sent" }, { delivery: "sent" }])).toEqual({ tone: "sent", label: "SENT · 2/2" });
  });
  test("some sent", () => {
    const s = deliverySummary([{ delivery: "sent" }, { delivery: "failed" }]);
    expect(s.tone).toBe("partial");
    expect(s.label).toBe("SENT TO 1 OF 2");
  });
  test("smtp unset", () => {
    const s = deliverySummary([{ delivery: "not_configured" }, { delivery: "not_configured" }]);
    expect(s.label).toBe("NOT SENT · EMAIL NOT CONFIGURED");
    expect(s.label).not.toMatch(/^SENT/);
  });
  test("failed and pending never read as sent", () => {
    expect(deliverySummary([{ delivery: "failed" }]).label).toMatch(/^NOT SENT/);
    expect(deliverySummary([{ delivery: "pending" }]).label).toMatch(/^NOT SENT/);
    expect(deliverySummary([]).label).toMatch(/^NOT SENT/);
  });
});

test("tokenFromHash reads only the fragment form", () => {
  expect(tokenFromHash("#token=abc123")).toBe("abc123");
  expect(tokenFromHash("#x=1&token=a%2Fb")).toBe("a/b");
  expect(tokenFromHash("")).toBeNull();
  expect(tokenFromHash("#token=")).toBeNull();
  expect(tokenFromHash("#other=1")).toBeNull();
  expect(tokenFromHash("#token=%E0%A4%A")).toBeNull();
});

describe("public routes", () => {
  afterEach(() => vi.unstubAllGlobals());

  test("post the token in the body, with no credentials or auth header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ acknowledged: true, project_name: "P", item_count: 2 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const r = await acknowledgeByToken("tok");
    expect(r.item_count).toBe(2);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/risk-acknowledgements\/acknowledge$/);
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("omit");
    expect(JSON.parse(init.body)).toEqual({ token: "tok" });
    expect(JSON.stringify(init.headers)).not.toMatch(/authorization/i);
    expect(String(url)).not.toContain("tok");
  });

  test("a 404 or 429 surfaces as ApiError and never touches the refresh path", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "This link is not valid" }), { status: 404 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "slow down" }), { status: 429 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(lookupAckToken("x")).rejects.toMatchObject({ status: 404 });
    await expect(lookupAckToken("x")).rejects.toBeInstanceOf(ApiError);
    // Exactly the two lookups; no /auth/refresh call in between.
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

test("filterByKind narrows the review queue client-side", () => {
  const mk = (kind: "false_positive" | "accepted_risk") => ({ review: { kind } }) as unknown as FindingReviewItem;
  const items = [mk("false_positive"), mk("accepted_risk"), mk("accepted_risk")];
  expect(filterByKind(items, "all")).toHaveLength(3);
  expect(filterByKind(items, "accepted_risk")).toHaveLength(2);
  expect(filterByKind(items, "false_positive")).toHaveLength(1);
});
