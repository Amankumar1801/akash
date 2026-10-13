import type { Channel, Direction, Phase, TriageCategory, VetStatus } from "../api/types";

// Plain-language names for the closed triage vocabulary. None of these says "discovery".
export const TRIAGE: Record<TriageCategory, { title: string; gist: string; tone: Direction }> = {
  known_confirmed: { title: "Already a confirmed planet",
    gist: "A curated archive lists a confirmed planet with this period.", tone: "neutral" },
  known_candidate: { title: "Already a catalogued candidate",
    gist: "An archive lists this signal as a candidate. It is not new.", tone: "neutral" },
  known_false_positive: { title: "Catalogued as a false positive",
    gist: "An archive has already ruled this signal out as a planet.", tone: "contradicts" },
  new_signal_review: { title: "Unlisted signal, worth a human look",
    gist: "No catalog match and no decisive vetting failure. This is a reason to look, not a result.",
    tone: "supports" },
  likely_systematic: { title: "Probably instrumental or stellar",
    gist: "Vetting found something that points away from a planet.", tone: "contradicts" },
  models_disagree: { title: "Models disagree, look manually",
    gist: "The classifiers split on this signal. The split is itself informative.",
    tone: "inconclusive" },
  insufficient_data: { title: "Not enough data to say",
    gist: "The data could not support a call either way.", tone: "inconclusive" },
};

export const CHANNELS: { id: Channel; name: string; blurb: string }[] = [
  { id: "observed_fact", name: "Measured in the data", blurb: "Computed deterministically from the light curve" },
  { id: "data_quality", name: "Data quality", blurb: "How far the data can be trusted" },
  { id: "model_prediction", name: "Model predictions", blurb: "Calibrated classifier output" },
  { id: "anomaly", name: "Anomaly engine", blurb: "How unusual against a stated reference population" },
  { id: "catalog_status", name: "Catalog status", blurb: "What curated archives already say" },
  { id: "cross_survey", name: "Cross-survey checks", blurb: "Stellar properties and nearby sources" },
  { id: "interpretation", name: "Interpretation", blurb: "Human or LLM commentary, never a source of fact" },
];

export const DIRECTION: Record<Direction, { word: string; mark: string }> = {
  supports: { word: "Supports a planet-scale signal", mark: "supports" },
  contradicts: { word: "Points away from a planet", mark: "contradicts" },
  neutral: { word: "Context", mark: "neutral" },
  inconclusive: { word: "Could not decide", mark: "inconclusive" },
};

export const VET: Record<VetStatus, string> = {
  pass: "Passed", warn: "Warning", fail: "Failed", unknown: "Could not run",
};

export const VET_CHECK_NAMES: Record<string, string> = {
  odd_even: "Odd and even transits match",
  secondary_eclipse: "No secondary eclipse",
  transit_shape: "Dip has a transit shape",
  periodicity_coverage: "Enough transits were observed",
  systematics_coincidence: "Not coincident with known instrument events",
  duration_plausibility: "Duration is possible for this star",
  depth_radius: "Depth implies a planet-sized object",
};
export const vetName = (id: string): string =>
  VET_CHECK_NAMES[id] ?? id.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

export const PHASE_NAMES: Record<Phase, { name: string; detail: string }> = {
  fetch_data: { name: "Fetch light curves", detail: "Download and validate archive data" },
  stellar_enrichment: { name: "Describe the star", detail: "Gaia radius, temperature, neighbours" },
  signal_search: { name: "Search for a signal", detail: "Detrend, then box-least-squares" },
  anomaly: { name: "Compare with the population", detail: "Four detectors, calibrated percentiles" },
  ml_inference: { name: "Classify", detail: "Council of models, calibrated, with a conformal set" },
  cross_match: { name: "Check the catalogs", detail: "TOI, KOI and the Exoplanet Archive" },
  evidence_fusion: { name: "Assemble the evidence", detail: "Typed rows, kept separate" },
  persist: { name: "Record provenance", detail: "Hash every input and step" },
};

export const RULE_TEXT: Record<string, string> = {
  no_catalog_match: "No catalog lists a signal at this period",
  vetting_no_decisive_failure: "No vetting check failed decisively",
  model_not_excluding: "The classifier does not rule a planet out",
  catalog_unavailable: "The catalog lookup was unavailable",
  models_disagree: "The classifiers disagree with each other",
  insufficient_data: "There was too little usable data",
};
export function ruleText(rule: string): string {
  if (rule.startsWith("catalog_period_match:")) {
    const kind = rule.split(":")[1];
    return `A catalog entry matches this period (${kind === "exact" ? "exactly" : kind})`;
  }
  if (rule.startsWith("vetting_fail:")) return `Vetting failed: ${vetName(rule.split(":")[1]).toLowerCase()}`;
  return RULE_TEXT[rule] ?? rule.replace(/[_:]/g, " ");
}
