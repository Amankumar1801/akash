import data from "./nl_rules.json";
import type { FeedQuery, TriageCategory } from "../api/types";

/** Browser twin of services/api/src/akash_api/nlquery.py. The rule table is exported from Python. */
export interface Interpretation {
  filters: { category: TriageCategory[]; exclude_known: boolean; min_anomaly_percentile: number | null; min_snr: number | null;
    reviewed: "any" | "reviewed" | "unreviewed"; q: string | null; sort: "triage" | "anomaly" | "snr" | "recent" };
  understood: { phrase: string; effect: string }[];
  unsupported: { phrase: string; why: string }[];
  not_understood: string[];
  notes: string[];
}
type Action = Record<string, unknown>;
const STOP = new Set<string>(data.stop);

export function interpret(input: string): Interpretation {
  let work = input.slice(0, data.max_text).toLowerCase();
  const cats = new Set<string>();
  const f: Interpretation["filters"] = { category: [], exclude_known: false, min_anomaly_percentile: null, min_snr: null,
    reviewed: "any", q: null, sort: "triage" };
  const understood: Interpretation["understood"] = [], unsupported: Interpretation["unsupported"] = [], notes: string[] = [];
  let sortSet = false;
  const max = (cur: number | null, v: number) => (cur === null ? v : Math.max(cur, v));
  for (const rule of data.rules as { pattern: string; action: Action; says: string }[]) {
    const rx = new RegExp(rule.pattern, "i");
    for (;;) {
      const m = rx.exec(work);
      if (!m || m[0].length === 0) break;
      const phrase = m[0].trim();
      work = work.slice(0, m.index) + " ".repeat(m[0].length) + work.slice(m.index + m[0].length);
      const a = rule.action, g = m.slice(1);
      let says = rule.says;
      g.forEach((v, i) => { says = says.replace(`{${i + 1}}`, i === 0 && "query" in a ? v.toUpperCase() : v); });
      if ("category" in a) (a.category as string[]).forEach((c) => cats.add(c));
      else if ("flag" in a) (f as unknown as Record<string, unknown>)[a.flag as string] = true;
      else if ("set" in a) {
        if (a.set === "sort") { if (sortSet) continue; sortSet = true; }
        (f as unknown as Record<string, unknown>)[a.set as string] = a.value;
      } else if ("min_anomaly" in a || "min_anomaly_capture" in a) {
        const v = Number("min_anomaly" in a ? a.min_anomaly : g[0]);
        if (v > 100) notes.push(`${phrase}: percentiles stop at 100, so 100 was used`);
        f.min_anomaly_percentile = max(f.min_anomaly_percentile, Math.min(v, 100));
      } else if ("min_snr" in a || "min_snr_capture" in a) {
        const v = Number("min_snr" in a ? a.min_snr : g[0]);
        if (v > 1000) notes.push(`${phrase}: the limit is 1000, so 1000 was used`);
        f.min_snr = max(f.min_snr, Math.min(v, 1000));
      } else if ("query" in a) {
        if (f.q === null) f.q = (a.query as string).replace("{1}", g[0].toUpperCase()).replace("{2}", g[1]);
      } else if ("unsupported" in a) { unsupported.push({ phrase, why: a.unsupported as string }); continue; }
      understood.push({ phrase, effect: says });
    }
  }
  f.category = [...cats].sort() as TriageCategory[];
  const left: string[] = [];
  for (const raw of work.match(/[a-z0-9_/.'-]+/g) ?? []) {
    const tok = raw.replace(/^[.'-]+|[.'-]+$/g, "");
    if (tok && !STOP.has(tok) && !left.includes(tok)) left.push(tok);
  }
  return { filters: f, understood, unsupported, not_understood: left, notes };
}

export function toFeedQuery(i: Interpretation, base: FeedQuery): FeedQuery {
  const f = i.filters;
  return { ...base, category: f.category.length ? f.category : undefined, exclude_known: f.exclude_known || undefined,
    min_anomaly_percentile: f.min_anomaly_percentile ?? undefined, min_snr: f.min_snr ?? undefined,
    reviewed: f.reviewed, q: f.q ?? undefined, sort: f.sort };
}
