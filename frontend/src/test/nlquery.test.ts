import { describe, expect, it } from "vitest";
import { DemoApi } from "../api/demo";
import { interpret, toFeedQuery } from "../lib/nlquery";
import cases from "./nl_cases.json";

describe("plain-language search (browser twin of the Python engine)", () => {
  it.each(cases.map((c) => [c.text, c.expect] as const))("matches Python for %j", (text, expect_) => {
    const got = interpret(text);
    expect(got.filters).toEqual(expect_.filters);
    expect(got.not_understood).toEqual(expect_.not_understood);
    expect(got.unsupported).toEqual(expect_.unsupported);
    expect(got.understood).toEqual(expect_.understood);
    expect(got.notes).toEqual(expect_.notes);
  });
  it("turns an interpretation into a feed query without inventing filters", () => {
    const q = toFeedQuery(interpret("new strong signals"), { sort: "triage", reviewed: "any" });
    expect(q.category).toEqual(["new_signal_review"]);
    expect(q.min_snr).toBe(15);
    expect(q.exclude_known).toBeUndefined();
    expect(toFeedQuery(interpret("banana"), { sort: "triage", reviewed: "any" }).category).toBeUndefined();
  });
  it("the demo api interprets and its feed honours the result", async () => {
    const api = new DemoApi();
    const i = await api.interpretQuery("new signals");
    const page = await api.discoveries({ ...toFeedQuery(i, { sort: "triage", reviewed: "any" }), limit: 50 });
    expect(page.items.every((c) => c.triage_category === "new_signal_review")).toBe(true);
  });
});
