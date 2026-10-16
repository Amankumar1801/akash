// Mirrors services/api schemas. Values the pipeline treats as open-ended stay `unknown`.
export type Mission = "kepler" | "tess";
export type Mode = "quick" | "deep";
export type TriageCategory =
  | "known_confirmed" | "known_candidate" | "known_false_positive" | "new_signal_review"
  | "likely_systematic" | "models_disagree" | "insufficient_data";
export type VetStatus = "pass" | "fail" | "warn" | "unknown";
export type Direction = "supports" | "contradicts" | "neutral" | "inconclusive";
export type Channel =
  | "observed_fact" | "catalog_status" | "model_prediction" | "anomaly" | "data_quality"
  | "cross_survey" | "interpretation";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface ObjectOut {
  object_id: string; canonical_name: string; ra_deg: number; dec_deg: number;
  anchor_namespace: string; aliases: { namespace: string; identifier: string }[];
}
export interface ObservationOut {
  obs_id: string; dataset: string; release: string | null; native_obs_id: string;
  modality: string; segment: number | null; retrieved_at: string;
}
export interface LightCurveData {
  obs_id: string; n_total: number; n_returned: number; downsampled: boolean;
  time_bjd: number[]; flux: (number | null)[]; quality_flagged: boolean[];
}
export interface InvestigationRequest {
  object_id?: string; query?: string; mission?: Mission; mode?: Mode;
  segments?: number[]; max_observations?: number;
}
export interface Job {
  investigation_id: string; status: JobStatus; created_at: number; started_at: number | null;
  finished_at: number | null; error: string | null; outcome: string | null;
  category: string | null; cancel_requested: boolean; deduplicated?: boolean;
  links: Record<string, string>;
}
export interface Interval { value: number; lo: number; hi: number }
export interface Assessment {
  investigation_id: string; object_id: string; triage_category: TriageCategory;
  triage_reasons: { rule: string; evidence_ids: string[] }[];
  transit: { period_d: Interval; depth_ppm: number; duration_h: number; snr: number;
    n_transits: number } | null;
  prediction: { planet_like_probability: number; interval_90: [number, number];
    calibrated: boolean; calibration_method: string | null; model_versions: string[];
    disagreement: { flag: boolean; range: number } | null } | null;
  anomaly: { percentile: number; reference_population: string; category: string;
    drivers: Record<string, number | string>[] } | null;
  data_quality: { grade: "A" | "B" | "C" | "D"; reasons: string[] };
  ood: { flag: boolean; distance_percentile: number | null } | null;
  vetting: Record<string, VetStatus>;
  known_status: { source: string; status: string; retrieved_at: string } | null;
  conflicting_evidence: string[]; recommended_followup: string[]; disclaimer_version: string;
}
export interface InvestigationDetail extends Job {
  object_id: string | null; assessment: Assessment | null; n_evidence: number | null;
}
export interface JobEvent { seq: number; ts: number; kind: string; data: Record<string, unknown> }
export interface EvidenceRow {
  evidence_id: string; channel: Channel; observation: string; result: Record<string, unknown>;
  uncertainty: Record<string, unknown> | null; reliability: string; agreement: Direction;
  timestamp: string; version: string; created_by: string;
  source: { source: string; activity?: string; uri: string | null; dataset: string | null;
    release: string | null; sha256: string | null };
  provenance_ids: string[];
}
export interface ProvNode {
  prov_id: string; entity_type: string; activity: string; code_version: string;
  sha256: string | null; source_uri: string | null; dataset: string | null;
  release: string | null; at: string;
}
export interface ProvGraph {
  nodes: ProvNode[]; edges: { from_prov: string; to_prov: string; relation: string }[];
  roots_verifiable: boolean;
}
export interface ModelOut {
  name: string; version: string; created_at: string | null; feature_version: string | null;
  data_hash: string | null; n: Record<string, number> | null;
}
export interface Me { name: string; role: string; key_id: string }

export const PHASES = ["fetch_data", "stellar_enrichment", "signal_search", "anomaly",
  "ml_inference", "cross_match", "evidence_fusion", "persist"] as const;
export type Phase = (typeof PHASES)[number];
export type PhaseStatus = "started" | "completed" | "failed" | "skipped";

export interface ReportFile { text: string; filename: string; mime: string }
export type StatementKind = "fact" | "prediction" | "interpretation" | "uncertainty" | "recommendation";
export interface AskAnswer {
  statements: { text: string; kind: StatementKind; evidence_ids: string[] }[];
  mode: "llm" | "deterministic"; verified: boolean; note: string | null;
  retrieved_evidence_ids: string[]; trace: { kind: string; [k: string]: unknown }[];
  disclaimer: string;
}

export interface ExperimentConfig {
  n_trials: number; n_controls: number; seed: number; period_min_d: number; period_max_d: number;
  depth_min_ppm: number; depth_max_ppm: number; noise_source: "synthetic";
}
export interface Rate { k: number; n: number; rate: number | null; lo: number | null; hi: number | null }
export interface RecoveryBin { label: string; lo: number; hi: number; recovered: Rate; alias_only: Rate }
export interface ExperimentResult {
  config: ExperimentConfig; config_sha256: string; noise_note: string; n_trials: number;
  overall_recovery: Rate; by_snr: RecoveryBin[]; by_period: RecoveryBin[]; by_depth: RecoveryBin[];
  snr_at_50pct: number | null; snr_at_90pct: number | null; false_alarm: Rate | null; caveats: string[];
}
export interface Experiment {
  experiment_id: string; status: JobStatus; created_at: number; started_at: number | null;
  finished_at: number | null; done: number; total: number; error: string | null;
  cancel_requested: boolean; config: ExperimentConfig; result: ExperimentResult | null;
}
export type ReviewLabel = "interesting" | "not_interesting" | "false_positive" | "needs_followup" | "uncertain";
export interface LabelRow {
  label_id: number; reviewer: string; label: ReviewLabel; note: string | null;
  triage_category: string | null; created_at: number;
}

export interface DiscoveryCard {
  investigation_id: string; object_id: string; name: string; ra_deg: number | null; dec_deg: number | null;
  triage_category: TriageCategory;
  anomaly: { percentile: number; reference_population: string; category: string } | null;
  prediction: { probability: number; interval_90: [number, number]; calibrated: boolean; models_disagree: boolean } | null;
  transit: { snr: number; period_d: number; depth_ppm: number } | null;
  signal_strength: "none" | "weak" | "moderate" | "strong";
  known_status: string | null; known_source: string | null; data_quality: "A" | "B" | "C" | "D";
  vetting: Record<string, number>; n_conflicts: number; recommended_followup: string[];
  finished_at: number | null;
  review: { n_reviewers: number; mine: ReviewLabel | null; labels: ReviewLabel[] };
}
export type FeedSort = "triage" | "anomaly" | "snr" | "recent";
export interface FeedQuery {
  category?: TriageCategory[]; exclude_known?: boolean; min_anomaly_percentile?: number; min_snr?: number;
  reviewed?: "any" | "reviewed" | "unreviewed"; q?: string; sort?: FeedSort; limit?: number; offset?: number;
}
export interface DiscoveryPage {
  items: DiscoveryCard[]; total: number; scanned: number; truncated: boolean;
  ranking: { sort: FeedSort; rule: string; caveat: string }; disclaimer: string;
}
export interface SkyPoint {
  investigation_id: string; name: string; ra_deg: number; dec_deg: number; category: TriageCategory;
  anomaly_percentile: number | null;
}
export interface SkyOut { points: SkyPoint[]; n: number; capped: boolean; truncated: boolean; note: string }

export interface SpectrumRequest {
  wavelength_a: number[]; flux: (number | null)[]; flux_err?: (number | null)[] | null; label?: string;
}
export interface SpectrumLine {
  wavelength_a: number; kind: "emission" | "absorption"; equivalent_width_a: number; snr: number;
  peak_sigma: number; fwhm_kms: number | null; n_pixels: number; matched: string | null;
}
export interface RedshiftCandidate {
  z: number; n_matched: number; z_scatter_kms: number;
  matched_lines: { rest: string; observed_a: number; offset_kms: number }[];
}
export type RedshiftStatus = "no_lines" | "single_line_only" | "no_match" | "candidate_redshift" | "ambiguous";
export interface SpectrumResult {
  input_sha256: string; n_points: number; n_masked: number; wavelength_range_a: [number, number];
  median_dispersion_a: number; noise_sigma: number; noise_source: "flux_err" | "mad";
  lines: SpectrumLine[];
  redshift: { status: RedshiftStatus; candidates: RedshiftCandidate[]; tier: "tentative" | "supported" | null; note: string };
  broad_emission: string[]; caveats: string[]; disclaimer: string; label?: string | null; precomputed?: boolean;
}
export type VariabilityCharacter = "insufficient_data" | "no_significant_variability" | "periodic_like" | "stochastic_aperiodic";
export interface VariabilityResult {
  character: VariabilityCharacter; reason: string | null; n_points: number; baseline_days?: number;
  excess_variance?: { nxs: number; nxs_err: number; fvar: number; significant: boolean };
  damped_random_walk?: { tau_d_days: number; sigma_frac: number; tau_d_reliable: boolean; note: string | null } | null;
  periodicity?: { best_period_d: number | null; periodic: boolean; n_cycles: number | null } | null;
  caveats: string[]; provenance_id?: string; input_sha256?: string; n_quality_dropped?: number; disclaimer?: string;
}
export interface ModelDetail { metadata: Record<string, unknown>; model_card: string | null }

export interface ImageRequest {
  fits_b64?: string; pixels_b64?: string; width?: number; height?: number; label?: string;
}
export interface ImageSource {
  centroid_xy: [number, number]; n_pixels: number; snr: number; flux: number; r20_px: number; r50_px: number;
  r80_px: number; concentration: number; asymmetry: number; ellipticity: number; position_angle_deg: number;
  aperture_radius_px: number;
}
export interface ImageResult {
  input_sha256: string; width: number; height: number; n_masked: number; background: number; noise_rms: number;
  status: "source_measured" | "no_source_detected"; source: ImageSource | null; caveats: string[]; disclaimer: string;
  preview: { width: number; height: number; factor: number; pixels_b64: string; vmin: number; vmax: number };
  label?: string | null; input_kind: "fits" | "pixels"; precomputed?: boolean;
}
