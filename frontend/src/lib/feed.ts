import type { Assessment, DiscoveryCard, DiscoveryPage, FeedQuery, FeedSort, ReviewLabel } from "../api/types";

// Same rules as the server (services/api/src/akash_api/discovery.py). Used by demo mode only.
export const TRIAGE_ORDER = ["new_signal_review", "models_disagree", "insufficient_data", "known_candidate",
  "likely_systematic", "known_false_positive", "known_confirmed"];
const KNOWN = new Set(["known_confirmed", "known_candidate", "known_false_positive"]);
export const RANKING_TEXT: Record<FeedSort, string> = {
  triage: "Ordered by triage category (unlisted signals and model disagreements first), then by anomaly percentile, then by recency.",
  anomaly: "Ordered by anomaly percentile within its reference population, then recency.",
  snr: "Ordered by the transit signal-to-noise, then recency.",
  recent: "Ordered by when the investigation finished.",
};
export const NOT_A_SCORE = "This is a review queue. The order says what to look at first, not how likely anything is to be real.";

export function signalStrength(snr: number | null): DiscoveryCard["signal_strength"] {
  return snr === null ? "none" : snr >= 15 ? "strong" : snr >= 7 ? "moderate" : "weak";
}

export function cardFrom(a: Assessment, name: string, ra: number, dec: number, invId: string,
  finished: number | null, mine: ReviewLabel | null): DiscoveryCard {
  const vet: Record<string, number> = { pass: 0, warn: 0, fail: 0, unknown: 0 };
  for (const v of Object.values(a.vetting)) vet[v] = (vet[v] ?? 0) + 1;
  return {
    investigation_id: invId, object_id: a.object_id, name, ra_deg: ra, dec_deg: dec,
    triage_category: a.triage_category,
    anomaly: a.anomaly ? { percentile: a.anomaly.percentile, reference_population: a.anomaly.reference_population, category: a.anomaly.category } : null,
    prediction: a.prediction ? { probability: a.prediction.planet_like_probability, interval_90: a.prediction.interval_90,
      calibrated: a.prediction.calibrated, models_disagree: !!a.prediction.disagreement?.flag } : null,
    transit: a.transit ? { snr: a.transit.snr, period_d: a.transit.period_d.value, depth_ppm: a.transit.depth_ppm } : null,
    signal_strength: signalStrength(a.transit?.snr ?? null),
    known_status: a.known_status?.status ?? null, known_source: a.known_status?.source ?? null,
    data_quality: a.data_quality.grade, vetting: vet, n_conflicts: a.conflicting_evidence.length,
    recommended_followup: a.recommended_followup.slice(0, 4), finished_at: finished,
    review: { n_reviewers: mine ? 1 : 0, mine, labels: mine ? [mine] : [] },
  };
}

const pct = (c: DiscoveryCard) => c.anomaly?.percentile ?? -1;
const snr = (c: DiscoveryCard) => c.transit?.snr ?? -1;
const rec = (c: DiscoveryCard) => c.finished_at ?? 0;

export function sortCards(cards: DiscoveryCard[], key: FeedSort): DiscoveryCard[] {
  const rank = (c: DiscoveryCard) => { const i = TRIAGE_ORDER.indexOf(c.triage_category); return i < 0 ? 99 : i; };
  const by: Record<FeedSort, (a: DiscoveryCard, b: DiscoveryCard) => number> = {
    anomaly: (a, b) => pct(b) - pct(a) || rec(b) - rec(a),
    snr: (a, b) => snr(b) - snr(a) || rec(b) - rec(a),
    recent: (a, b) => rec(b) - rec(a),
    triage: (a, b) => rank(a) - rank(b) || pct(b) - pct(a) || rec(b) - rec(a),
  };
  return [...cards].sort(by[key]);
}

export function applyFeed(cards: DiscoveryCard[], q: FeedQuery): DiscoveryPage {
  const cats = new Set(q.category ?? []);
  const rows = sortCards(cards.filter((c) => {
    if (cats.size && !cats.has(c.triage_category)) return false;
    if (q.exclude_known && (KNOWN.has(c.triage_category) || ["confirmed", "candidate", "false_positive"].includes(c.known_status ?? ""))) return false;
    if (q.min_anomaly_percentile !== undefined && (c.anomaly === null || c.anomaly.percentile < q.min_anomaly_percentile)) return false;
    if (q.min_snr !== undefined && (c.transit === null || c.transit.snr < q.min_snr)) return false;
    if (q.reviewed === "reviewed" && !c.review.mine) return false;
    if (q.reviewed === "unreviewed" && c.review.mine) return false;
    if (q.q && !c.name.toLowerCase().includes(q.q.toLowerCase())) return false;
    return true;
  }), q.sort ?? "triage");
  const off = q.offset ?? 0, lim = q.limit ?? 25, sort = q.sort ?? "triage";
  return { items: rows.slice(off, off + lim), total: rows.length, scanned: cards.length, truncated: false,
    ranking: { sort, rule: RANKING_TEXT[sort], caveat: NOT_A_SCORE },
    disclaimer: "AKASH assists investigation; it does not independently establish discoveries." };
}
