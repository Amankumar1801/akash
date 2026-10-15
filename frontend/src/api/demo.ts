// A browser-side stand-in for the API. Everything here is synthetic, generated deterministically,
// and shown with a permanent "demo data" banner. The IDs (TIC 9000000xx) do not exist in any archive.
import type { AkashApi } from "./client";
import { ApiError } from "./client";
import { minmaxIndices } from "../lib/lc";
import type {
  AskAnswer, DiscoveryCard, DiscoveryPage, FeedQuery, SkyOut, Assessment, Experiment, ExperimentConfig, LabelRow, ReviewLabel, Direction, EvidenceRow, InvestigationDetail, InvestigationRequest, Job, JobEvent,
  JobStatus, LightCurveData, Me, ModelOut, ObjectOut, ObservationOut, Phase, ProvGraph, ProvNode,
  TriageCategory, VetStatus, ModelDetail, SpectrumRequest, SpectrumResult, VariabilityResult,
} from "./types";
import sample from "./spectrum_sample.json";
import { PHASES } from "./types";
import { demoReport } from "../lib/report";
import { applyFeed, cardFrom } from "../lib/feed";

export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const gauss = (r: () => number): number =>
  Math.sqrt(-2 * Math.log(1 - r())) * Math.cos(2 * Math.PI * r());

type Shape = "transit" | "eb" | "none";
export interface Scenario {
  id: number; title: string; summary: string; shape: Shape; period: number; depthPpm: number;
  durationH: number; noisePpm: number; triage: TriageCategory | null; prob: number;
  interval: [number, number]; disagree?: number; anomalyPct: number; anomalyCat: string;
  grade: "A" | "B" | "C" | "D"; vet: Record<string, VetStatus>;
  known: "none" | "confirmed" | "candidate" | "false_positive" | "unavailable";
  ood?: boolean; followups: string[]; teff: number; radius: number; nearby?: boolean;
}

export const SCENARIOS: Scenario[] = [
  { id: 1, title: "A clean periodic dip, not in any catalog",
    summary: "The case AKASH exists for. Still only a reason to look.", shape: "transit",
    period: 3.42, depthPpm: 2100, durationH: 2.7, noisePpm: 380, triage: "new_signal_review",
    prob: 0.91, interval: [0.82, 0.96], anomalyPct: 54, anomalyCat: "typical_variability",
    grade: "A", vet: { odd_even: "pass", secondary_eclipse: "pass", transit_shape: "pass",
      periodicity_coverage: "pass", systematics_coincidence: "pass", duration_plausibility: "pass",
      depth_radius: "pass" }, known: "none", followups: [], teff: 5650, radius: 0.97 },
  { id: 2, title: "A signal an archive already confirms",
    summary: "Matches a confirmed planet's period. AKASH reports the catalog, it confirms nothing.",
    shape: "transit", period: 5.71, depthPpm: 4400, durationH: 3.1, noisePpm: 320,
    triage: "known_confirmed", prob: 0.97, interval: [0.93, 0.99], anomalyPct: 41,
    anomalyCat: "typical_variability", grade: "A", vet: { odd_even: "pass", secondary_eclipse: "pass",
      transit_shape: "pass", periodicity_coverage: "pass", systematics_coincidence: "pass",
      duration_plausibility: "pass", depth_radius: "pass" }, known: "confirmed", followups: [],
    teff: 5210, radius: 0.88 },
  { id: 3, title: "A signal already listed as a candidate",
    summary: "An archive lists this period as a candidate. Not new.", shape: "transit",
    period: 8.9, depthPpm: 1400, durationH: 3.6, noisePpm: 420, triage: "known_candidate",
    prob: 0.84, interval: [0.7, 0.93], anomalyPct: 63, anomalyCat: "typical_variability",
    grade: "B", vet: { odd_even: "pass", secondary_eclipse: "pass", transit_shape: "pass",
      periodicity_coverage: "warn", systematics_coincidence: "pass", duration_plausibility: "pass",
      depth_radius: "pass" }, known: "candidate", followups: [], teff: 4890, radius: 0.74 },
  { id: 4, title: "A signal an archive has already ruled out",
    summary: "The period matches a catalogued false positive.", shape: "transit", period: 2.31,
    depthPpm: 6100, durationH: 1.9, noisePpm: 350, triage: "known_false_positive", prob: 0.77,
    interval: [0.58, 0.9], anomalyPct: 72, anomalyCat: "eclipse_like", grade: "A",
    vet: { odd_even: "warn", secondary_eclipse: "pass", transit_shape: "pass",
      periodicity_coverage: "pass", systematics_coincidence: "pass", duration_plausibility: "pass",
      depth_radius: "warn" }, known: "false_positive", followups: [], teff: 6020, radius: 1.21 },
  { id: 5, title: "A deep, V-shaped eclipse with a secondary",
    summary: "Odd and even dips differ: an eclipsing binary at twice this period is likelier.",
    shape: "eb", period: 4.18, depthPpm: 14500, durationH: 4.2, noisePpm: 450,
    triage: "likely_systematic", prob: 0.31, interval: [0.18, 0.49], anomalyPct: 96,
    anomalyCat: "eclipse_like", grade: "B", vet: { odd_even: "fail", secondary_eclipse: "fail",
      transit_shape: "warn", periodicity_coverage: "pass", systematics_coincidence: "pass",
      duration_plausibility: "pass", depth_radius: "fail" }, known: "none", ood: true,
    followups: ["Compare odd/even transit depths with more transits (eclipsing binary at twice this period?)",
      "Classifier inputs are out-of-distribution: rely on vetting and manual review"],
    teff: 5900, radius: 1.1 },
  { id: 6, title: "The classifiers split",
    summary: "One model sees a planet, another does not. The disagreement is the finding.",
    shape: "transit", period: 6.27, depthPpm: 1700, durationH: 3.3, noisePpm: 520,
    triage: "models_disagree", prob: 0.55, interval: [0.2, 0.86], disagree: 0.62, anomalyPct: 81,
    anomalyCat: "unusual_shape", grade: "B", vet: { odd_even: "pass", secondary_eclipse: "pass",
      transit_shape: "warn", periodicity_coverage: "pass", systematics_coincidence: "pass",
      duration_plausibility: "pass", depth_radius: "pass" }, known: "none",
    followups: ["Models disagree strongly: review the folded light curve by eye before anything else"],
    teff: 5400, radius: 0.92 },
  { id: 7, title: "A good signal, but the catalogs were down",
    summary: "AKASH says so plainly and asks for the lookup to be repeated.", shape: "transit",
    period: 11.4, depthPpm: 2600, durationH: 4.4, noisePpm: 390, triage: "new_signal_review",
    prob: 0.88, interval: [0.76, 0.95], anomalyPct: 47, anomalyCat: "typical_variability",
    grade: "A", vet: { odd_even: "pass", secondary_eclipse: "pass", transit_shape: "pass",
      periodicity_coverage: "warn", systematics_coincidence: "pass", duration_plausibility: "pass",
      depth_radius: "pass" }, known: "unavailable",
    followups: ["Catalog lookup was unavailable: re-check TOI/KOI/Exoplanet Archive status"],
    teff: 5780, radius: 1.0 },
  { id: 8, title: "No periodic signal at all",
    summary: "The search found nothing above the noise, and says so.", shape: "none", period: 0,
    depthPpm: 0, durationH: 0, noisePpm: 420, triage: null, prob: 0, interval: [0, 0],
    anomalyPct: 0, anomalyCat: "", grade: "A", vet: {}, known: "none", followups: [], teff: 5500,
    radius: 0.9 },
];

const norm = (q: string): string => q.toUpperCase().replace(/\s+/g, " ").trim();
export function scenarioFor(query: string): Scenario {
  const m = /^(?:TIC|DEMO)[ -]?(\d+)$/.exec(norm(query));
  if (m && Number(m[1]) >= 900000001 && Number(m[1]) <= 900000008) return SCENARIOS[Number(m[1]) - 900000001];
  let h = 2166136261;
  for (const ch of norm(query)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return SCENARIOS[(h >>> 0) % SCENARIOS.length];
}

export function synthLightCurve(s: Scenario, seed: number): LightCurveData {
  const r = rng(seed), dt = 10 / 1440, n = Math.floor(27.4 / dt);
  const time: number[] = [], flux: (number | null)[] = [], flagged: boolean[] = [];
  let red = 0;
  const t0 = s.period * 0.37 + 0.4, dur = s.durationH / 24;
  for (let i = 0; i < n; i++) {
    const t = 2459000 + i * dt, rel = i * dt;
    if (rel > 13.2 && rel < 14.2) continue; // the gap between orbits
    red = 0.985 * red + 90e-6 * gauss(r);
    let f = 1 + red + (s.noisePpm * 1e-6) * gauss(r) + 320e-6 * Math.sin((2 * Math.PI * rel) / 6.1);
    if (s.shape !== "none") {
      const ph = ((((rel - t0) / s.period) % 1) + 1) % 1, x = Math.min(ph, 1 - ph) * s.period;
      const k = Math.round((rel - t0) / s.period), odd = k % 2 !== 0;
      if (s.shape === "transit") {
        const ing = dur * 0.18;
        if (x < dur / 2) f -= s.depthPpm * 1e-6 * Math.min(1, (dur / 2 - x) / ing);
      } else if (x < dur / 2) { // V-shaped eclipse, odd ones deeper
        f -= s.depthPpm * 1e-6 * (1 - x / (dur / 2)) * (odd ? 1 : 0.62);
      } else {
        const x2 = Math.abs(ph - 0.5) * s.period;
        if (x2 < dur / 2) f -= s.depthPpm * 0.28e-6 * (1 - x2 / (dur / 2));
      }
    }
    time.push(t); flux.push(f * 15200); flagged.push(r() < 0.012);
  }
  return { obs_id: "", n_total: time.length, n_returned: time.length, downsampled: false,
    time_bjd: time, flux, quality_flagged: flagged };
}

// ---- evidence + provenance ---------------------------------------------------------------
const uuid = (): string => crypto.randomUUID();
const sha = (r: () => number): string =>
  Array.from({ length: 64 }, () => "0123456789abcdef"[Math.floor(r() * 16)]).join("");

export interface Built { evidence: EvidenceRow[]; prov: ProvGraph; assessment: Assessment | null }

export function buildInvestigation(s: Scenario, ids: { inv: string; obj: string }, seed: number): Built {
  const r = rng(seed), now = new Date().toISOString();
  const P = (activity: string, type: string, extra: Partial<ProvNode> = {}): ProvNode => ({
    prov_id: uuid(), entity_type: type, activity, code_version: "akash-science 0.2.0",
    sha256: sha(r), source_uri: null, dataset: null, release: null, at: now, ...extra });
  const mast = P("download", "raw_light_curve", { source_uri: "mast:TESS/product/demo-lc.fits",
    dataset: "TESS SPOC", release: "Sector 74", code_version: "akash-data 0.1.0" });
  const gaia = P("cone_search", "catalog_row", { source_uri: "https://gea.esac.esa.int/tap-server/tap",
    dataset: "Gaia DR3", release: "DR3", code_version: "akash-data 0.1.0" });
  const cat = P("catalog_query", "catalog_row", { source_uri: "https://exoplanetarchive.ipac.caltech.edu/TAP",
    dataset: "NASA Exoplanet Archive", release: "live table", code_version: "akash-data 0.1.0" });
  const norm_ = P("normalise", "light_curve");
  const detr = P("biweight_detrend", "light_curve");
  const bls = P("bls_search", "signal");
  const clf = P("transit_classifier", "prediction", { code_version: "akash-ml 0.3.0 transit-council/v1" });
  const anom = P("anomaly_ensemble", "anomaly", { code_version: "akash-ml 0.3.0 anomaly/v1" });
  const nodes = [mast, gaia, cat, norm_, detr, bls, clf, anom];
  const E = (a: ProvNode, b: ProvNode, relation = "wasDerivedFrom") =>
    ({ from_prov: a.prov_id, to_prov: b.prov_id, relation });
  const edges = [E(norm_, mast), E(detr, norm_), E(bls, detr), E(clf, bls), E(anom, detr)];
  if (s.known !== "unavailable") edges.push({ from_prov: cat.prov_id, to_prov: bls.prov_id, relation: "used" });

  const root = (n: ProvNode) => ({ source: n.dataset ?? n.activity, activity: n.activity,
    uri: n.source_uri, dataset: n.dataset, release: n.release, sha256: n.sha256 });
  const rows: EvidenceRow[] = [], tagged: Record<string, string[]> = {};
  const add = (tag: string, channel: EvidenceRow["channel"], observation: string,
    result: Record<string, unknown>, agreement: Direction, from: ProvNode, by: string,
    reliability = "pipeline_derived", uncertainty: Record<string, unknown> | null = null) => {
    const id = uuid();
    (tagged[tag] ??= []).push(id);
    rows.push({ evidence_id: id, channel, observation, result, uncertainty, reliability, agreement,
      timestamp: now, version: by, created_by: reliability === "model_output" ? "model" : "tool",
      source: root(from === bls || from === clf || from === anom ? mast : from),
      provenance_ids: [from.prov_id] });
  };
  if (s.shape === "none") {
    add("snr", "observed_fact", "Box-least-squares found no periodic dip above the noise floor",
      { best_snr: 4.1, threshold: 7.1 }, "inconclusive", bls, "akash-science 0.2.0");
    add("dq", "data_quality", "Light curve is usable: 2 sectors, 1.2% of points flagged",
      { grade: s.grade, n_points: 3880 }, "neutral", norm_, "akash-science 0.2.0");
    return { evidence: rows, prov: { nodes: [mast, norm_, detr, bls], edges: edges.slice(0, 3),
      roots_verifiable: true }, assessment: null };
  }
  const T = s.period, snr = (s.depthPpm / s.noisePpm) * Math.sqrt(Math.max(1, (27 / T) * (s.durationH * 3 / 24 * 144)));
  add("signal", "observed_fact", `A periodic dip repeats every ${T.toFixed(3)} d`,
    { period_d: T, n_transits: Math.floor(27 / T) }, "supports", bls, "akash-science 0.2.0", "pipeline_derived",
    { period_lo: T - 0.002, period_hi: T + 0.002 });
  add("depth", "observed_fact", `Dips are ${s.depthPpm} ppm deep and last ${s.durationH} h`,
    { depth_ppm: s.depthPpm, duration_h: s.durationH }, "neutral", bls, "akash-science 0.2.0");
  add("snr", "observed_fact", `Signal-to-noise is ${snr.toFixed(1)}`, { snr: +snr.toFixed(1) },
    snr > 7.1 ? "supports" : "inconclusive", bls, "akash-science 0.2.0");
  for (const [name, st] of Object.entries(s.vet)) {
    const d: Direction = st === "pass" ? "supports" : st === "fail" ? "contradicts" : "inconclusive";
    add(`vet:${name}`, "observed_fact", `Vetting check ${name.replace(/_/g, " ")}: ${st}`,
      { check: name, status: st }, d, bls, "akash-science 0.2.0/vetting v1");
  }
  add("dq", "data_quality", `Data grade ${s.grade}: 2 sectors, 1.2% of points flagged`,
    { grade: s.grade }, "neutral", norm_, "akash-science 0.2.0");
  add("model", "model_prediction",
    `Planet-like probability ${(s.prob * 100).toFixed(0)}% (90% set ${(s.interval[0] * 100).toFixed(0)} to ${(s.interval[1] * 100).toFixed(0)}%)`,
    { probability: s.prob, calibrated: true }, s.prob >= 0.5 ? "supports" : "contradicts", clf,
    "transit-council/v1", "model_output", { interval_90: s.interval });
  if (s.disagree) add("disagree", "model_prediction",
    `Council members disagree: probabilities span ${(s.disagree * 100).toFixed(0)} points`,
    { range: s.disagree }, "inconclusive", clf, "transit-council/v1", "model_output");
  add("anomaly", "anomaly", `Unusual at the ${s.anomalyPct}th percentile of the synthetic reference population`,
    { percentile: s.anomalyPct, category: s.anomalyCat }, "neutral", anom, "anomaly/v1", "model_output");
  add("gaia", "cross_survey", `Gaia DR3: Teff ${s.teff} K, radius ${s.radius} Rsun`,
    { teff_k: s.teff, radius_rsun: s.radius }, "neutral", gaia, "akash-data 0.1.0", "archive_curated");
  add("gaia", "cross_survey", "No Gaia neighbour within 42 arcsec bright enough to cause this dip",
    { n_neighbours: 0 }, "supports", gaia, "akash-fusion 0.4.0", "archive_curated");
  if (s.known === "unavailable") {
    add("catalog", "catalog_status", "Catalog lookup failed: the archive did not respond",
      { error: "timeout" }, "inconclusive", cat, "akash-data 0.1.0", "archive_curated");
  } else if (s.known === "none") {
    add("catalog", "catalog_status", "No TOI, KOI or Exoplanet Archive entry matches this period",
      { n_matches: 0 }, "neutral", cat, "akash-fusion 0.4.0", "archive_curated");
  } else {
    const word = { confirmed: "confirmed planet", candidate: "planet candidate", false_positive: "false positive" }[s.known];
    add("catalog", "catalog_status", `NASA Exoplanet Archive lists a ${word} at ${T.toFixed(3)} d`,
      { status: s.known, source: "NASA Exoplanet Archive", match: "exact" },
      s.known === "false_positive" ? "contradicts" : "supports", cat, "akash-fusion 0.4.0", "archive_curated");
  }
  if (s.ood) add("ood", "model_prediction", "Features sit far outside the training population (OOD)",
    { distance_percentile: 99.2 }, "inconclusive", clf, "transit-council/v1", "model_output");

  const failed = Object.entries(s.vet).find(([, v]) => v === "fail")?.[0];
  const rule = (name: string, tags: string[]) =>
    ({ rule: name, evidence_ids: tags.flatMap((t) => tagged[t] ?? []).slice(0, 4) });
  const reasons = s.triage === "known_confirmed" || s.triage === "known_candidate" || s.triage === "known_false_positive"
    ? [rule("catalog_period_match:exact", ["catalog"])]
    : s.triage === "likely_systematic" ? [rule(`vetting_fail:${failed}`, [`vet:${failed}`])]
    : s.triage === "models_disagree" ? [rule("models_disagree", ["disagree"])]
    : [rule(s.known === "unavailable" ? "catalog_unavailable" : "no_catalog_match", ["catalog"]),
       rule("vetting_no_decisive_failure", Object.keys(s.vet).map((k) => `vet:${k}`)),
       rule("model_not_excluding", ["model"])];
  const knownMap = { none: "none", confirmed: "confirmed", candidate: "candidate",
    false_positive: "false_positive", unavailable: "" } as const;
  const assessment: Assessment = {
    investigation_id: ids.inv, object_id: ids.obj, triage_category: s.triage as TriageCategory,
    triage_reasons: reasons,
    transit: { period_d: { value: T, lo: T - 0.002, hi: T + 0.002 }, depth_ppm: s.depthPpm,
      duration_h: s.durationH, snr: +snr.toFixed(1), n_transits: Math.floor(27 / T) },
    prediction: { planet_like_probability: s.prob, interval_90: s.interval, calibrated: true,
      calibration_method: "isotonic", model_versions: ["lightgbm/v1", "cnn1d/v1"],
      disagreement: s.disagree ? { flag: true, range: s.disagree } : { flag: false, range: 0.08 } },
    anomaly: { percentile: s.anomalyPct, reference_population: "synthetic demo population (n=2,000)",
      category: s.anomalyCat, drivers: [] },
    data_quality: { grade: s.grade, reasons: s.grade === "A" ? [] : ["Short baseline: fewer than 4 transits"] },
    ood: { flag: !!s.ood, distance_percentile: s.ood ? 99.2 : 41 }, vetting: s.vet,
    known_status: s.known === "unavailable" ? null : { source: "NASA Exoplanet Archive",
      status: knownMap[s.known], retrieved_at: now },
    conflicting_evidence: rows.filter((e) => e.agreement === "contradicts").map((e) => e.evidence_id),
    recommended_followup: s.followups, disclaimer_version: "v1" };
  return { evidence: rows, prov: { nodes, edges, roots_verifiable: true }, assessment };
}

// ---- the fake service ---------------------------------------------------------------------
interface DemoJob { job: Job; params: InvestigationRequest; object: ObjectOut; scenario: Scenario;
  built: Built; events: JobEvent[]; lc: LightCurveData; obs: ObservationOut; cancel: boolean }

const sleep = (ms: number, signal?: AbortSignal) => new Promise<void>((res) => {
  const t = setTimeout(res, ms);
  signal?.addEventListener("abort", () => { clearTimeout(t); res(); }, { once: true });
});

export class DemoApi implements AkashApi {
  readonly kind = "demo" as const;
  private jobs = new Map<string, DemoJob>();
  private objects = new Map<string, ObjectOut>();
  private scenarioOf = new Map<string, Scenario>();
  /** Milliseconds per phase; tests set this to 0. */
  constructor(private pace = 650, seed = true) {
    if (seed) for (const [n, ago] of [[2, 7200], [5, 2400], [1, 300]] as const) this.seedJob(n, ago);
  }

  private makeObject(query: string, s: Scenario): ObjectOut {
    const key = `${s.id}:${norm(query)}`;
    const existing = this.objects.get(key);
    if (existing) return existing;
    const r = rng(s.id * 7919);
    const tic = /^(?:TIC|DEMO)[ -]?(\d+)$/.exec(norm(query))?.[1] ?? String(900000000 + s.id);
    const isId = /^(?:TIC|DEMO)[ -]?\d+$/.test(norm(query));
    const o: ObjectOut = { object_id: uuid(), canonical_name: isId ? `TIC ${tic}` : `Demo target: ${query.trim()}`, ra_deg: +(r() * 360).toFixed(5),
      dec_deg: +(r() * 120 - 60).toFixed(5), anchor_namespace: "TIC",
      aliases: [{ namespace: "TIC", identifier: tic }, { namespace: "Gaia DR3", identifier: String(4e18 + Math.floor(r() * 1e15)) }] };
    this.objects.set(key, o); this.objects.set(o.object_id, o); this.scenarioOf.set(o.object_id, s);
    return o;
  }

  private mint(object: ObjectOut, s: Scenario, params: InvestigationRequest, ageS = 0): DemoJob {
    const inv = uuid(), seed = s.id * 1000 + 17, now = Date.now() / 1000 - ageS;
    const built = buildInvestigation(s, { inv, obj: object.object_id }, seed);
    const lc = synthLightCurve(s, seed);
    const obs: ObservationOut = { obs_id: uuid(), dataset: "TESS SPOC (synthetic)", release: "demo",
      native_obs_id: `demo-s${74 + s.id}`, modality: "light_curve", segment: 74, retrieved_at: new Date(now * 1000).toISOString() };
    lc.obs_id = obs.obs_id;
    const job: Job = { investigation_id: inv, status: "queued", created_at: now, started_at: null,
      finished_at: null, error: null, outcome: null, category: null, cancel_requested: false,
      links: {} };
    const d: DemoJob = { job, params, object, scenario: s, built, events: [], lc, obs, cancel: false };
    this.jobs.set(inv, d);
    return d;
  }

  private seedJob(n: number, ageS: number) {
    const s = SCENARIOS[n - 1], o = this.makeObject(`TIC ${900000000 + n}`, s);
    const d = this.mint(o, s, { object_id: o.object_id, mission: "tess", mode: "deep" }, ageS);
    void this.run(d, 0);
  }

  private push(d: DemoJob, kind: string, data: Record<string, unknown>) {
    d.events.push({ seq: d.events.length + 1, ts: Date.now() / 1000, kind, data });
  }

  private async run(d: DemoJob, pace: number, signal?: AbortSignal) {
    const s = d.scenario, j = d.job;
    j.status = "running"; j.started_at = Date.now() / 1000;
    this.push(d, "job_started", { trace_id: j.investigation_id });
    const skipAfterSignal = s.shape === "none";
    const msgs: Record<Phase, string> = {
      fetch_data: `2 TESS light curves, ${d.lc.n_total.toLocaleString("en-US")} points`,
      stellar_enrichment: `Teff ${s.teff} K, R ${s.radius} Rsun from Gaia DR3`,
      signal_search: s.shape === "none" ? "no peak above threshold" : `best period ${s.period.toFixed(3)} d`,
      anomaly: s.shape === "none" ? "" : `${s.anomalyPct}th percentile`,
      ml_inference: s.shape === "none" ? "" : `p = ${s.prob.toFixed(2)}`,
      cross_match: s.known === "unavailable" ? "archive unavailable" : "3 catalogs queried",
      evidence_fusion: `${d.built.evidence.length} evidence rows`, persist: "provenance chain verified" };
    for (const phase of PHASES) {
      if (d.cancel || signal?.aborted) break;
      const skip = skipAfterSignal && ["anomaly", "ml_inference", "cross_match"].includes(phase);
      const failed = phase === "cross_match" && s.known === "unavailable";
      this.push(d, "phase", { phase, status: skip ? "skipped" : "started", message: skip ? "no signal to analyse" : "", data: {} });
      if (skip) continue;
      await sleep(pace * (0.6 + 0.5 * ((phase.length * 7) % 5) / 5));
      if (d.cancel) break;
      this.push(d, "phase", { phase, status: failed ? "failed" : "completed", message: msgs[phase], data: {} });
    }
    j.finished_at = Date.now() / 1000;
    if (d.cancel) {
      j.status = "cancelled"; this.push(d, "job_cancelled", {});
    } else {
      j.status = "succeeded";
      j.outcome = s.shape === "none" ? "no_transit_signal" : "assessed";
      j.category = d.built.assessment?.triage_category ?? null;
      this.push(d, "job_succeeded", { outcome: j.outcome, category: j.category, warnings: [] });
    }
  }

  private detail(d: DemoJob): InvestigationDetail {
    const done = d.job.status === "succeeded";
    return { ...d.job, object_id: d.object.object_id, assessment: done ? d.built.assessment : null,
      n_evidence: done ? d.built.evidence.length : null,
      links: { self: "", events: "", log: "", evidence: "", provenance: "" } };
  }
  private get(id: string): DemoJob {
    const d = this.jobs.get(id);
    if (!d) throw new ApiError(404, "not_found", "investigation not found");
    return d;
  }

  async me(): Promise<Me> { return { name: "demo", role: "researcher", key_id: "demo" }; }
  async searchObject(query: string): Promise<ObjectOut> {
    await sleep(250);
    if (!query.trim()) throw new ApiError(422, "validation_failed", "Enter a name or catalog ID.");
    return this.makeObject(query, scenarioFor(query));
  }
  async getObject(id: string): Promise<ObjectOut> {
    const o = this.objects.get(id);
    if (!o) throw new ApiError(404, "object_not_found", "object not found");
    return o;
  }
  async observations(objectId: string): Promise<ObservationOut[]> {
    return [...this.jobs.values()].filter((d) => d.object.object_id === objectId).slice(0, 1).map((d) => d.obs);
  }
  async observationData(obsId: string, maxPoints: number): Promise<LightCurveData> {
    const d = [...this.jobs.values()].find((x) => x.obs.obs_id === obsId);
    if (!d) throw new ApiError(404, "not_found", "observation not found");
    const f = d.lc.flux.map((v) => v ?? 0), idx = minmaxIndices(f, maxPoints);
    return { ...d.lc, n_returned: idx.length, downsampled: idx.length < d.lc.n_total,
      time_bjd: idx.map((i) => d.lc.time_bjd[i]), flux: idx.map((i) => d.lc.flux[i]),
      quality_flagged: idx.map((i) => d.lc.quality_flagged[i]) };
  }
  async createInvestigation(req: InvestigationRequest): Promise<Job> {
    const o = req.object_id ? await this.getObject(req.object_id) : await this.searchObject(req.query ?? "");
    const s = this.scenarioOf.get(o.object_id) ?? scenarioFor(o.canonical_name);
    const dup = [...this.jobs.values()].find((d) => d.object.object_id === o.object_id && d.job.status !== "failed" && d.job.status !== "cancelled");
    if (dup) return { ...dup.job, deduplicated: true };
    const d = this.mint(o, s, req);
    void this.run(d, this.pace);
    return { ...d.job };
  }
  async listInvestigations(): Promise<Job[]> {
    return [...this.jobs.values()].map((d) => ({ ...d.job })).sort((a, b) => b.created_at - a.created_at);
  }
  async getInvestigation(id: string) { return this.detail(this.get(id)); }
  async cancelInvestigation(id: string): Promise<Job> {
    const d = this.get(id);
    if (["succeeded", "failed", "cancelled"].includes(d.job.status))
      throw new ApiError(409, "already_finished", `investigation already ${d.job.status}`);
    d.cancel = true; d.job.cancel_requested = true;
    return { ...d.job };
  }
  async evidence(id: string) { return this.get(id).built.evidence; }
  private labels = new Map<string, LabelRow[]>();
  /** Demo feed: every scenario appears, so the queue has something to rank. */
  private async ensureAll() {
    for (let n = 1; n <= SCENARIOS.length; n++) {
      const s = SCENARIOS[n - 1], o = this.makeObject(`TIC ${900000000 + n}`, s);
      if ([...this.jobs.values()].some((d) => d.object.object_id === o.object_id)) continue;
      const d = this.mint(o, s, { object_id: o.object_id, mission: "tess", mode: "deep" }, 600 * n);
      await this.run(d, 0);
    }
  }
  private cards(): DiscoveryCard[] {
    const seen = new Set<string>(), out: DiscoveryCard[] = [];
    const ds = [...this.jobs.values()].sort((a, b) => (b.job.finished_at ?? 0) - (a.job.finished_at ?? 0));
    for (const d of ds) {
      const a = d.built.assessment;
      if (d.job.status !== "succeeded" || !a || seen.has(d.object.object_id)) continue;
      seen.add(d.object.object_id);
      const hist = this.labels.get(d.job.investigation_id) ?? [];
      out.push(cardFrom(a, d.object.canonical_name, d.object.ra_deg, d.object.dec_deg, d.job.investigation_id,
        d.job.finished_at, hist.length ? hist[hist.length - 1].label : null));
    }
    return out;
  }
  async discoveries(q: FeedQuery): Promise<DiscoveryPage> { await this.ensureAll(); return applyFeed(this.cards(), q); }
  async sky(): Promise<SkyOut> {
    await this.ensureAll();
    const pts = this.cards().filter((c) => c.ra_deg !== null && c.dec_deg !== null).map((c) => ({
      investigation_id: c.investigation_id, name: c.name, ra_deg: c.ra_deg as number, dec_deg: c.dec_deg as number,
      category: c.triage_category, anomaly_percentile: c.anomaly?.percentile ?? null }));
    return { points: pts, n: pts.length, capped: false, truncated: false,
      note: "Only objects that have been investigated appear here. This is not a survey map." };
  }
  async createExperiment(_c: ExperimentConfig): Promise<Experiment> {
    throw new ApiError(501, "needs_live_api",
      "The experiment lab runs the real pipeline, so it needs the live API. Demo data has no pipeline to test.");
  }
  async getExperiment(_id: string): Promise<Experiment> { throw new ApiError(404, "not_found", "experiment not found"); }
  async cancelExperiment(_id: string): Promise<Experiment> { throw new ApiError(404, "not_found", "experiment not found"); }
  async addLabel(id: string, label: ReviewLabel, note?: string): Promise<LabelRow> {
    const d = this.get(id);
    const row: LabelRow = { label_id: (this.labels.get(id)?.length ?? 0) + 1, reviewer: "demo", label,
      note: note ?? null, triage_category: d.built.assessment?.triage_category ?? null, created_at: Date.now() / 1000 };
    this.labels.set(id, [...(this.labels.get(id) ?? []), row]);
    return row;
  }
  async listLabels(id: string): Promise<LabelRow[]> { this.get(id); return [...(this.labels.get(id) ?? [])]; }
  async report(id: string, format: "markdown" | "html") {
    const d = this.get(id);
    return demoReport(d.object.canonical_name, d.built.assessment ?? null, d.built.evidence, format);
  }
  async ask(id: string, question: string): Promise<AskAnswer> {
    const { evidence } = this.get(id).built;
    if (!question.trim()) throw new ApiError(422, "validation_error", "ask a question");
    const fact = new Set(["observed_fact", "data_quality", "catalog_status", "cross_survey"]);
    const pick = (chs: string[]) => evidence.filter((e) => chs.includes(e.channel)).slice(0, 3);
    const st: AskAnswer["statements"] = [];
    for (const e of pick(["catalog_status", "observed_fact", "data_quality"]))
      st.push({ text: e.observation.replace(/\.$/, ""), kind: fact.has(e.channel) ? "fact" : "prediction", evidence_ids: [e.evidence_id] });
    const models = pick(["model_prediction", "anomaly"]);
    for (const e of models) st.push({ text: e.observation.replace(/\.$/, ""), kind: "prediction", evidence_ids: [e.evidence_id] });
    if (models.length) st.push({ text: "Model outputs are predictions with stated uncertainty, not measurements.", kind: "uncertainty", evidence_ids: [models[0].evidence_id] });
    if (!st.length) st.push({ text: "There is no evidence to summarise for this investigation.", kind: "recommendation", evidence_ids: [] });
    return { statements: st, mode: "deterministic", verified: true, note: null,
      retrieved_evidence_ids: st.flatMap((s) => s.evidence_ids), trace: [],
      disclaimer: "AKASH assists investigation; it does not independently establish discoveries." };
  }
  async provenance(id: string): Promise<ProvGraph> { return this.get(id).built.prov; }
  async models(): Promise<ModelOut[]> {
    return [
      { name: "transit-council", version: "v1", created_at: "2026-10-01T09:00:00Z", feature_version: "f3",
        data_hash: "9f2c1a77d0be", n: { train: 4200, val: 900, test: 900 } },
      { name: "anomaly-ensemble", version: "v1", created_at: "2026-10-03T12:30:00Z", feature_version: "a2",
        data_hash: "41be90cc27aa", n: { reference: 2000, calibration: 500 } },
    ];
  }
  async modelDetail(name: string, version: string): Promise<ModelDetail> {
    const m = (await this.models()).find((x) => x.name === name && x.version === version);
    if (!m) throw new ApiError(404, "not_found", "model not found");
    return { metadata: { ...m, note: "Demo registry entry. Real entries also carry training metrics." },
      model_card: `# ${name} ${version}\n\nDemo model card. A real card records training data, metrics, calibration and limits.` };
  }
  async analyzeSpectrum(req: SpectrumRequest): Promise<SpectrumResult> {
    const same = req.wavelength_a.length === sample.wavelength_a.length && req.wavelength_a[0] === sample.wavelength_a[0]
      && req.flux.every((v, i) => v === sample.flux[i]);
    if (!same) throw new ApiError(501, "demo_unavailable", "Demo mode can only show its built-in sample spectrum. Connect to a live API to analyse your own.");
    return { ...(sample.analysis as unknown as SpectrumResult), label: req.label ?? null, precomputed: true };
  }
  async variability(_obsId: string): Promise<VariabilityResult> {
    throw new ApiError(501, "demo_unavailable", "Variability descriptors need a live API.");
  }
  async *events(id: string, after: number, signal: AbortSignal): AsyncGenerator<JobEvent> {
    const d = this.get(id);
    let last = after;
    while (!signal.aborted) {
      for (const e of d.events.slice(last)) {
        last = e.seq; yield e;
        if (["job_succeeded", "job_failed", "job_cancelled"].includes(e.kind)) return;
      }
      await sleep(60, signal);
    }
  }
}

export const STATUS_DONE: JobStatus[] = ["succeeded", "failed", "cancelled"];
