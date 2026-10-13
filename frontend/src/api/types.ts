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
