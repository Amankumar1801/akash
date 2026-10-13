import { describe, expect, it } from "vitest";
import { parseSseBlock } from "../api/client";
import { DemoApi, SCENARIOS, synthLightCurve } from "../api/demo";
import type { AkashApi } from "../api/client";
import type { JobEvent } from "../api/types";
import { layout } from "../components/ProvGraph";
import { follow } from "../lib/follow";
import { binFold, cleanSeries, estimateEpoch, minmaxIndices, niceTicks, phaseOf } from "../lib/lc";
import { ruleText, TRIAGE } from "../lib/labels";
import { reduceLanes } from "../lib/phases";

describe("light-curve helpers", () => {
  it("min/max downsampling keeps a single-sample dip that a stride would drop", () => {
    const y = new Array(10000).fill(1); y[5003] = 0.9;
    const idx = minmaxIndices(y, 200);
    expect(idx.length).toBeLessThanOrEqual(200);
    expect(idx).toContain(5003);
  });
  it("is a no-op when the data already fits", () => {
    expect(minmaxIndices([1, 2, 3], 10)).toEqual([0, 1, 2]);
  });
  it("phaseOf puts mid-transit at zero and stays in [-0.5, 0.5)", () => {
    expect(phaseOf(10, 2, 10)).toBeCloseTo(0);
    expect(phaseOf(11, 2, 10)).toBeCloseTo(-0.5);
    for (const t of [-3.3, 0, 7.77, 100.1]) { const p = phaseOf(t, 2.5, 0.3); expect(p).toBeGreaterThanOrEqual(-0.5); expect(p).toBeLessThan(0.5); }
  });
  it("cleanSeries drops flagged and null samples and normalises by the median", () => {
    const s = cleanSeries([1, 2, 3, 4], [10, null, 12, 1000], [false, false, false, true]);
    expect(s.t).toEqual([1, 3]);
    expect(s.f[0] + s.f[1]).toBeCloseTo(2, 1);
  });
  it("recovers the display epoch of a synthetic transit to within a transit duration", () => {
    const s = SCENARIOS[0], lc = synthLightCurve(s, 1017);
    const ser = cleanSeries(lc.time_bjd, lc.flux, lc.quality_flagged);
    const t0 = estimateEpoch(ser, s.period);
    const truth = 2459000 + s.period * 0.37 + 0.4;
    const off = Math.abs(((t0 - truth) / s.period + 0.5) % 1 - 0.5) * s.period;
    expect(off).toBeLessThan(s.durationH / 24);
    const b = binFold(ser, s.period, t0, 60);
    expect(Math.min(...b.flux)).toBeLessThan(1 - s.depthPpm * 1e-6 * 0.5);
  });
  it("niceTicks stays inside the range and is monotone", () => {
    const t = niceTicks(-1234, 2210, 5);
    expect(t[0]).toBeGreaterThanOrEqual(-1234); expect(t[t.length - 1]).toBeLessThanOrEqual(2210);
    expect(t.every((v, i) => i === 0 || v > t[i - 1])).toBe(true);
  });
});

describe("events", () => {
  it("parses SSE blocks, ignores keepalives and the end marker", () => {
    const e = parseSseBlock('id: 3\nevent: phase\ndata: {"phase":"anomaly","status":"started","ts":12.5}');
    expect(e).toMatchObject({ seq: 3, kind: "phase", ts: 12.5 });
    expect(parseSseBlock(": keepalive")).toBeNull();
    expect(parseSseBlock("event: end\ndata: {}")).toBeNull();
    expect(parseSseBlock("id: 1\nevent: x\ndata: {not json")).toBeNull();
  });
  it("reduces events to one state per phase and ignores unknown phases", () => {
    const ev = (seq: number, phase: string, status: string, message = ""): JobEvent => ({ seq, ts: 0, kind: "phase", data: { phase, status, message } });
    const lanes = reduceLanes([ev(1, "fetch_data", "started"), ev(2, "fetch_data", "completed", "2 curves"),
      ev(3, "signal_search", "started"), ev(4, "anomaly", "skipped"), ev(5, "brand_new_phase", "started")]);
    const by = Object.fromEntries(lanes.map((l) => [l.phase, l]));
    expect(by.fetch_data).toMatchObject({ state: "done", message: "2 curves" });
    expect(by.signal_search.state).toBe("running");
    expect(by.anomaly.state).toBe("skipped");
    expect(by.persist.state).toBe("pending");
    expect(lanes).toHaveLength(8);
  });
  it("follow() resumes after a dropped connection without losing or repeating events", async () => {
    const all: JobEvent[] = [1, 2, 3, 4].map((n) => ({ seq: n, ts: 0, kind: n === 4 ? "job_succeeded" : "phase", data: {} }));
    let calls = 0;
    const api = { async *events(_id: string, after: number) {
      calls++;
      for (const e of all.filter((x) => x.seq > after)) {
        if (calls === 1 && e.seq === 3) throw new Error("connection reset");
        yield e;
      }
    } } as unknown as AkashApi;
    const seen: number[] = [];
    const res = await follow(api, "x", (e) => seen.push(e.seq), new AbortController().signal);
    expect(res).toBe("done");
    expect(seen).toEqual([1, 2, 3, 4]);
    expect(calls).toBe(2);
  });
  it("follow() gives up and says so when the stream never recovers", async () => {
    const api = { async *events() { throw new Error("down"); yield undefined as never; } } as unknown as AkashApi;
    expect(await follow(api, "x", () => undefined, new AbortController().signal, 1)).toBe("lost");
  });
});

describe("labels", () => {
  it("never calls anything a discovery", () => {
    const text = JSON.stringify(TRIAGE).toLowerCase();
    expect(text).not.toMatch(/discover|proves|confirmed new/);
  });
  it("explains rules in plain language and falls back safely", () => {
    expect(ruleText("catalog_period_match:exact")).toMatch(/matches this period/);
    expect(ruleText("vetting_fail:odd_even")).toMatch(/odd and even/i);
    expect(ruleText("some_future_rule")).toBe("some future rule");
  });
});

describe("provenance layout", () => {
  it("puts raw sources left of what was derived from them", () => {
    const n = (id: string) => ({ prov_id: id, entity_type: "x", activity: id, code_version: "", sha256: null, source_uri: null, dataset: null, release: null, at: "" });
    const { pos } = layout({ nodes: [n("raw"), n("mid"), n("out")], roots_verifiable: true,
      edges: [{ from_prov: "mid", to_prov: "raw", relation: "wasDerivedFrom" }, { from_prov: "out", to_prov: "mid", relation: "wasDerivedFrom" }] });
    expect(pos.get("raw")!.x).toBeLessThan(pos.get("mid")!.x);
    expect(pos.get("mid")!.x).toBeLessThan(pos.get("out")!.x);
  });
  it("survives a cycle instead of looping", () => {
    const n = (id: string) => ({ prov_id: id, entity_type: "x", activity: id, code_version: "", sha256: null, source_uri: null, dataset: null, release: null, at: "" });
    expect(() => layout({ nodes: [n("a"), n("b")], roots_verifiable: false,
      edges: [{ from_prov: "a", to_prov: "b", relation: "r" }, { from_prov: "b", to_prov: "a", relation: "r" }] })).not.toThrow();
  });
});

describe("demo service", () => {
  const run = async (api: DemoApi, query: string) => {
    const job = await api.createInvestigation({ query });
    const seen: JobEvent[] = [];
    await follow(api, job.investigation_id, (e) => seen.push(e), new AbortController().signal);
    return { id: job.investigation_id, seen, detail: await api.getInvestigation(job.investigation_id) };
  };
  it.each(SCENARIOS.map((s) => [s.id, s]))("scenario %i ends in its designed triage with cited, existing evidence", async (_n, s) => {
    const api = new DemoApi(0, false);
    const { id, seen, detail } = await run(api, `TIC ${900000000 + s.id}`);
    expect(seen.at(-1)?.kind).toBe("job_succeeded");
    expect(seen.map((e) => e.seq)).toEqual(seen.map((_, i) => i + 1)); // ordered, gapless
    if (s.triage === null) {
      expect(detail.outcome).toBe("no_transit_signal"); expect(detail.assessment).toBeNull();
      expect(reduceLanes(seen).filter((l) => l.state === "skipped").map((l) => l.phase)).toEqual(["anomaly", "ml_inference", "cross_match"]);
      return;
    }
    const a = detail.assessment!, ev = await api.evidence(id), ids = new Set(ev.map((e) => e.evidence_id));
    expect(a.triage_category).toBe(s.triage);
    for (const r of a.triage_reasons) { expect(r.evidence_ids.length).toBeGreaterThan(0); for (const x of r.evidence_ids) expect(ids.has(x)).toBe(true); }
    for (const x of a.conflicting_evidence) expect(ids.has(x)).toBe(true);
    expect(JSON.stringify(a)).not.toMatch(/"score"/); // there is no combined score anywhere
    const prov = await api.provenance(id), pids = new Set(prov.nodes.map((n) => n.prov_id));
    for (const e of ev) for (const p of e.provenance_ids) expect(pids.has(p)).toBe(true);
  });
  it("keeps contradicting findings visible in the false-positive and eclipsing-binary cases", async () => {
    const api = new DemoApi(0, false);
    for (const n of [4, 5]) {
      const { id } = await run(api, `TIC ${900000000 + n}`);
      expect((await api.evidence(id)).some((e) => e.agreement === "contradicts")).toBe(true);
    }
  });
  it("is idempotent for the same target and honest about catalog outages", async () => {
    const api = new DemoApi(0, false);
    const a = await api.createInvestigation({ query: "TIC 900000007" });
    const b = await api.createInvestigation({ query: "TIC 900000007" });
    expect(b.investigation_id).toBe(a.investigation_id); expect(b.deduplicated).toBe(true);
    const { id, seen } = await run(api, "TIC 900000007");
    expect(reduceLanes(seen).find((l) => l.phase === "cross_match")?.state).toBe("failed");
    const d = await api.getInvestigation(id);
    expect(d.assessment?.known_status).toBeNull(); // unknown, not "no entry"
    expect(d.assessment?.recommended_followup.join(" ")).toMatch(/unavailable/);
  });
  it("labels arbitrary queries as demo targets and never as the real object", async () => {
    const api = new DemoApi(0, false);
    const o = await api.searchObject("Kepler-22");
    expect(o.canonical_name).toBe("Demo target: Kepler-22");
  });
  it("cancels a running investigation and refuses to cancel a finished one", async () => {
    const api = new DemoApi(40, false);
    const job = await api.createInvestigation({ query: "TIC 900000003" });
    await api.cancelInvestigation(job.investigation_id);
    await follow(api, job.investigation_id, () => undefined, new AbortController().signal);
    expect((await api.getInvestigation(job.investigation_id)).status).toBe("cancelled");
    await expect(api.cancelInvestigation(job.investigation_id)).rejects.toMatchObject({ code: "already_finished" });
  });
  it("downsamples observation data to the requested size", async () => {
    const api = new DemoApi(0, false);
    const { detail } = await run(api, "TIC 900000001");
    const obs = await api.observations(detail.object_id as string);
    const lc = await api.observationData(obs[0].obs_id, 500);
    expect(lc.n_returned).toBeLessThanOrEqual(500); expect(lc.downsampled).toBe(true);
  });
});

describe("demo ask", () => {
  it("answers only from the investigation's own evidence", async () => {
    const api = new DemoApi(0, false);
    const j = await api.createInvestigation({ query: "TIC 1" });
    for (let k = 0; k < 400; k++) {
      if ((await api.getInvestigation(j.investigation_id)).status === "succeeded") break;
      await new Promise((r) => setTimeout(r, 5));
    }
    const ev = new Set((await api.evidence(j.investigation_id)).map((x) => x.evidence_id));
    const a = await api.ask(j.investigation_id, "what is uncertain?");
    expect(a.verified).toBe(true);
    for (const s of a.statements) for (const id of s.evidence_ids) expect(ev.has(id)).toBe(true);
    expect(a.statements.every((s) => !/discover/i.test(s.text))).toBe(true);
  });
});

describe("demo report", () => {
  it("cites only existing evidence, escapes markup and carries the disclaimer", async () => {
    const api = new DemoApi(0, false);
    const j = await api.createInvestigation({ query: "TIC 1" });
    for (let k = 0; k < 400; k++) {
      if ((await api.getInvestigation(j.investigation_id)).status === "succeeded") break;
      await new Promise((r) => setTimeout(r, 5));
    }
    const ev = new Set((await api.evidence(j.investigation_id)).map((x) => x.evidence_id.slice(0, 8)));
    const md = (await api.report(j.investigation_id, "markdown")).text;
    for (const m of md.matchAll(/\[([0-9a-f]{8})\]/g)) expect(ev.has(m[1])).toBe(true);
    expect(md).toContain("does not independently establish discoveries");
    const html = (await api.report(j.investigation_id, "html")).text;
    expect(html).not.toMatch(/<script/i);
  });
});
