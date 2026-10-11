"""Investigation orchestrator: light curve + object -> typed evidence -> triage -> Assessment.

This is the deterministic Deep Dive. The LLM (Phase 8) narrates and explains its outputs; it never
computes any of them. Every external dependency is optional and degrades to an explicit
'unavailable' finding rather than a silent omission."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from akash_core.enums import Direction, EvidenceChannel, ReliabilityClass
from akash_core.errors import AkashError
from akash_core.ids import new_id
from akash_core.schemas import (
    Assessment,
    AstronomicalObject,
    Evidence,
    KnownStatus,
    OODInfo,
    Prediction,
    TransitSummary,
    TriageReason,
)
from akash_core.schemas.assessment import Interval
from akash_data.base import CatalogRecord
from akash_data.lightcurve import NormalizedLightCurve
from akash_data.storage import LocalArtifactStore
from akash_ml.anomaly.engine import AnomalyEngine, AnomalyResult
from akash_ml.training import TrainedSystem
from akash_ml.transit.infer import dataset_from_results, ephemeris_result_from_pipeline
from akash_ml.uncertainty.quality import grade_quality
from akash_provenance import SqliteProvenanceStore
from akash_science.lightcurve.pipeline import LightCurvePipeline, PipelineResult
from akash_science.lightcurve.types import TCE
from akash_science.persist import persist_result

from .catalog_match import match_signal, star_entry_summary
from .evidence import (
    EvidenceRecorder,
    _tool,
    add_anomaly_evidence,
    add_catalog_evidence,
    add_model_evidence,
    add_quality_evidence,
    add_signal_evidence,
    add_stellar_evidence,
)
from .matrix import evidence_matrix
from .progress import ProgressCallback, ProgressEvent
from .stellar import StellarProfile, StellarService, assess_contamination
from .store import EvidenceStore
from .triage import ModelView, TriageConfig, TriageDecision, TriageInputs, triage


class CatalogLookup(Protocol):
    name: str
    url: str
    last_queries: list[str]

    def lookup(self, obj: AstronomicalObject) -> list[CatalogRecord]: ...


@dataclass
class InvestigationDeps:
    pipeline: LightCurvePipeline
    prov: SqliteProvenanceStore
    artifacts: LocalArtifactStore
    code_version: str
    store: EvidenceStore | None = None
    system: TrainedSystem | None = None
    anomaly: AnomalyEngine | None = None
    catalog: CatalogLookup | None = None
    stellar: StellarService | None = None
    triage_cfg: TriageConfig = field(default_factory=TriageConfig)


@dataclass
class InvestigationResult:
    investigation_id: UUID
    outcome: str  # "assessed" | "no_transit_signal"
    assessment: Assessment | None
    evidence: list[Evidence]
    decision: TriageDecision | None
    pipeline: PipelineResult
    anomaly: AnomalyResult | None
    additional_signals: list[TCE]
    warnings: list[str]

    def matrix(self, prov: SqliteProvenanceStore) -> list[dict[str, Any]]:
        return evidence_matrix(self.evidence, prov)


def _dropped_fraction(counts: dict[str, int]) -> float:
    n = max(counts.get("input", 0), 1)
    lost = sum(counts.get(k, 0) for k in
               ("dropped_flagged", "dropped_nonfinite", "dropped_short_segments", "clipped_upward"))
    return min(lost / n, 1.0)


def investigate(obj: AstronomicalObject, lc: NormalizedLightCurve, lc_prov_id: UUID,
                deps: InvestigationDeps, investigation_id: UUID | None = None,
                progress: ProgressCallback | None = None) -> InvestigationResult:
    inv = investigation_id or new_id()

    def emit(phase: str, status: str, message: str = "", **data: Any) -> None:
        if progress is not None:
            progress(ProgressEvent(phase, status, message, dict(data)))

    rec = EvidenceRecorder(inv, deps.prov, deps.code_version)
    warnings: list[str] = []

    profile: StellarProfile | None = None
    if deps.stellar is None:
        emit("stellar_enrichment", "skipped", "no Gaia service configured")
    else:
        emit("stellar_enrichment", "started")
        try:
            profile = deps.stellar.profile(obj)
            emit("stellar_enrichment", "completed" if profile else "skipped",
                 "" if profile else "no Gaia source for this object")
        except AkashError as e:
            warnings.append(f"Gaia enrichment unavailable: {e}")
            emit("stellar_enrichment", "failed", "Gaia enrichment unavailable")

    emit("signal_search", "started")
    res = deps.pipeline.run(lc, stellar=profile.context() if profile else None)
    pipe_rec, _, _ = persist_result(res, lc_prov_id, deps.artifacts, deps.prov, deps.code_version)
    pipeline_prov = pipe_rec.prov_id
    emit("signal_search", "completed", f"{len(res.tces)} periodic signal(s) found",
         n_tces=len(res.tces), n_points=len(res.time))

    anomaly: AnomalyResult | None = None
    if deps.anomaly is None:
        emit("anomaly", "skipped", "no reference population configured")
    else:
        emit("anomaly", "started")
        anomaly = deps.anomaly.analyze(lc)
        add_anomaly_evidence(rec, anomaly, [lc_prov_id])
        emit("anomaly", "completed", anomaly.status.value)

    if not res.tces:
        warnings.extend(res.warnings)
        for phase in ("ml_inference", "cross_match", "evidence_fusion"):
            emit(phase, "skipped", "no transit signal to assess")
        out = InvestigationResult(inv, "no_transit_signal", None, rec.items, None, res, anomaly,
                                  [], warnings)
        emit("persist", "started")
        if deps.store:
            deps.store.save(None, rec.items, inv)
        emit("persist", "completed")
        return out

    primary, extras = res.tces[0], [t.tce for t in res.tces[1:]]
    t = primary.tce
    add_signal_evidence(rec, res, primary, lc_prov_id, pipeline_prov)
    for extra in extras:  # other periodic signals are findings too, but are not triaged here
        pa = rec.derived("tce", f"{res.version}:tce{extra.rank}", [pipeline_prov])
        rec.add(f"extra:{extra.rank}", EvidenceChannel.OBSERVED_FACT, Direction.NEUTRAL,
                f"Additional periodic signal: P={extra.period_d:.4f} d, depth "
                f"{extra.depth_ppm:.0f} ppm, SNR {extra.snr:.1f} (not triaged in this assessment)",
                {"period_d": extra.period_d, "depth_ppm": extra.depth_ppm, "snr": extra.snr},
                ReliabilityClass.PIPELINE_DERIVED, _tool("lc-pipeline", res.version), [pa])

    dq = grade_quality(t.snr, t.n_transits, t.beta, _dropped_fraction(res.counts))
    add_quality_evidence(rec, dq, [pipeline_prov])

    model_view: ModelView | None = None
    prediction: Prediction | None = None
    ood: OODInfo | None = None
    if deps.system is None:
        emit("ml_inference", "skipped", "no classifier configured")
    else:
        emit("ml_inference", "started")
        er = ephemeris_result_from_pipeline(res, primary)
        scored = deps.system.score(dataset_from_results([er]))
        add_model_evidence(rec, deps.system, scored, 0, [pipeline_prov])
        prediction, ood = deps.system.to_prediction(scored, 0)
        model_view = ModelView(float(scored.prob[0]), scored.set_labels[0],
                               bool(scored.ood_flag[0]), bool(scored.disagree[0]),
                               rec.keys["model"])
        emit("ml_inference", "completed", scored.set_labels[0])

    records: list[CatalogRecord] = []
    catalog_available, known_source = False, "NASA Exoplanet Archive"
    emit("cross_match", "started")
    if deps.catalog is not None:
        try:
            records = deps.catalog.lookup(obj)
            catalog_available = True
        except AkashError as e:
            warnings.append(f"catalog lookup failed: {e}")
    match = match_signal(t.period_d, records) if catalog_available else None
    if catalog_available:
        add_catalog_evidence(rec, records, match, known_source, deps.catalog.url,  # type: ignore[union-attr]
                             list(deps.catalog.last_queries), t.period_d)  # type: ignore[union-attr]
    else:
        p = rec.root("catalog_query", "query:unavailable", "unavailable",
                     {"configured": deps.catalog is not None})
        rec.add("catalog:unavailable", EvidenceChannel.CATALOG_STATUS, Direction.INCONCLUSIVE,
                "Catalog lookup unavailable: novelty of this signal is unverified",
                {"source": known_source, "status": "unavailable"},
                ReliabilityClass.UNKNOWN, _tool("catalog-lookup", "n/a"), [p])

    cont = None
    if profile is not None:
        cont = assess_contamination(profile, t.depth_frac)
        add_stellar_evidence(rec, profile, cont)
    emit("cross_match", "completed" if catalog_available else "failed",
         "catalog matched" if match else "no catalog match" if catalog_available
         else "catalog unavailable")
    emit("evidence_fusion", "started")

    cat_key = ("catalog:match" if match else "catalog:summary" if records
               else "catalog:none" if catalog_available else "catalog:unavailable")
    tin = TriageInputs(
        quality_grade=dq.grade, quality_evidence=rec.keys["quality"], n_transits=t.n_transits,
        signal_evidence=rec.keys["signal"], vetting={v.name: v.status for v in primary.vetting},
        vetting_evidence={v.name: rec.keys[f"vet:{v.name}"] for v in primary.vetting},
        catalog_match=match, catalog_evidence=rec.keys.get(cat_key),
        catalog_available=catalog_available,
        star_has_other_entries=bool(records) and match is None, model=model_view,
        anomaly_artifact_suspect=bool(anomaly and anomaly.status.value == "artifact_suspect"),
        anomaly_evidence=rec.keys.get("anomaly"), contamination=cont,
        contamination_evidence=rec.keys.get("gaia:contamination"),
        binarity_suspect=profile.binarity_suspect if profile else None,
        binarity_evidence=rec.keys.get("gaia:ruwe"))
    decision = triage(tin, deps.triage_cfg)

    lo, hi = t.period_interval_d
    assessment = Assessment(
        investigation_id=inv, object_id=obj.object_id, triage_category=decision.category,
        triage_reasons=[TriageReason(rule=r.rule, evidence_ids=r.evidence_ids)
                        for r in decision.reasons],
        transit=TransitSummary(
            period_d=Interval(value=t.period_d, lo=min(lo, t.period_d), hi=max(hi, t.period_d)),
            depth_ppm=t.depth_ppm, duration_h=t.duration_d * 24.0, snr=t.snr,
            n_transits=t.n_transits),
        prediction=prediction, anomaly=anomaly.to_core() if anomaly else None, data_quality=dq,
        ood=ood, vetting={v.name: v.status for v in primary.vetting},
        known_status=KnownStatus(
            source=known_source, status=match.status if match else "none",
            retrieved_at=datetime.now(UTC).isoformat()) if catalog_available else None,
        conflicting_evidence=[e.evidence_id for e in rec.items
                              if e.direction == Direction.CONTRADICTS],
        recommended_followup=decision.followups)
    emit("evidence_fusion", "completed", decision.category.value,
         category=decision.category.value)
    emit("persist", "started")
    if deps.store:
        deps.store.save(assessment, rec.items, inv)
    emit("persist", "completed")
    return InvestigationResult(inv, "assessed", assessment, rec.items, decision, res, anomaly,
                               extras, warnings)


__all__ = ["CatalogLookup", "InvestigationDeps", "InvestigationResult", "investigate",
           "star_entry_summary"]
