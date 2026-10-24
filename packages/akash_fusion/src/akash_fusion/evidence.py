"""Evidence recorder + builders. Every finding becomes an immutable, typed Evidence row whose
provenance ids lead back to a fetch (source_uri + sha256) or to the deterministic derivation.

Direction is relative to ONE hypothesis, stated once here so it is never ambiguous:
    H = "the detected signal is an astrophysical, planet-scale transit-like signal"
SUPPORTS / CONTRADICTS say how a finding bears on H; NEUTRAL means context; INCONCLUSIVE means the
check could not decide. Nothing here is summed or weighted."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from akash_core import __version__
from akash_core.enums import (
    CreatorType,
    Direction,
    EvidenceChannel,
    ProvRelation,
    ReliabilityClass,
    VetStatus,
)
from akash_core.ids import params_hash
from akash_core.schemas import DataQuality, Evidence, ProvenanceRecord
from akash_core.schemas.evidence import Creator
from akash_data.base import CatalogRecord
from akash_ml.anomaly.engine import AnomalyResult, AnomalyStatus
from akash_ml.training import Scored, TrainedSystem
from akash_provenance import SqliteProvenanceStore
from akash_science.lightcurve.pipeline import PipelineResult, TCEResult

from .catalog_match import CatalogMatch, record_period
from .stellar import ContaminationAssessment, StellarProfile

_VET_DIR = {VetStatus.PASS: Direction.SUPPORTS, VetStatus.WARN: Direction.CONTRADICTS,
            VetStatus.FAIL: Direction.CONTRADICTS, VetStatus.UNKNOWN: Direction.INCONCLUSIVE}


@dataclass
class EvidenceRecorder:
    investigation_id: UUID
    prov: SqliteProvenanceStore
    code_version: str
    items: list[Evidence] = field(default_factory=list)
    keys: dict[str, UUID] = field(default_factory=dict)

    # ---- provenance helpers ----
    def derived(self, entity_type: str, activity: str, parents: list[UUID], *,
                sha256: str | None = None, dataset: str | None = None,
                release: str | None = None) -> UUID:
        rec = self.prov.add(ProvenanceRecord(
            entity_type=entity_type, activity=activity, code_version=self.code_version,
            sha256=sha256, dataset=dataset, release=release))
        for p in parents:
            self.prov.link(rec.prov_id, p, ProvRelation.WAS_DERIVED_FROM)
        return rec.prov_id

    def root(self, entity_type: str, activity: str, source_uri: str, content: Any,
             dataset: str | None = None) -> UUID:
        """A provenance ROOT: needs a source and a content hash to be verifiable."""
        rec = self.prov.add(ProvenanceRecord(
            entity_type=entity_type, activity=activity, code_version=self.code_version,
            sha256=params_hash(content), source_uri=source_uri, dataset=dataset))
        return rec.prov_id

    def catalog_prov(self, rec: CatalogRecord) -> UUID:
        return self.root("catalog_row", f"query:{rec.source}:{rec.table}", rec.source_uri,
                         {"query": rec.query, "values": rec.values}, rec.table)

    # ---- core ----
    def add(self, key: str, channel: EvidenceChannel, direction: Direction, claim: str,
            value: dict[str, Any], reliability: ReliabilityClass, creator: Creator,
            prov_ids: list[UUID], uncertainty: dict[str, Any] | None = None) -> Evidence:
        ev = Evidence(
            investigation_id=self.investigation_id, channel=channel, direction=direction,
            claim=claim, value=value, uncertainty=uncertainty, reliability=reliability,
            provenance_ids=tuple(prov_ids), created_by=creator)
        self.items.append(ev)
        self.keys[key] = ev.evidence_id
        return ev


def _tool(name: str, version: str) -> Creator:
    return Creator(type=CreatorType.TOOL, name=name, version=version)


def add_signal_evidence(rec: EvidenceRecorder, res: PipelineResult, tr: TCEResult,
                        lc_prov: UUID, pipeline_prov: UUID) -> None:
    t = tr.tce
    pa = rec.derived("tce", f"{res.version}:tce{t.rank}", [pipeline_prov])
    rec.add("signal", EvidenceChannel.OBSERVED_FACT, Direction.SUPPORTS,
            f"Periodic dip search found P={t.period_d:.4f} d, depth {t.depth_ppm:.0f} ppm, "
            f"duration {t.duration_d * 24:.2f} h, SNR {t.snr:.1f}, {t.n_transits} transits",
            {"period_d": t.period_d, "depth_ppm": t.depth_ppm, "duration_h": t.duration_d * 24,
             "snr": t.snr, "n_transits": t.n_transits, "t0_bjd": t.t0_bjd, "beta": t.beta},
            ReliabilityClass.PIPELINE_DERIVED, _tool("lc-pipeline", res.version), [pa],
            uncertainty={"period_interval_d": list(t.period_interval_d),
                         "note": "interval is a heuristic dlogL region, not calibrated"})
    for v in tr.vetting:
        rec.add(f"vet:{v.name}", EvidenceChannel.OBSERVED_FACT, _VET_DIR[v.status],
                f"{v.name}: {v.summary}", {"check": v.name, "status": v.status.value, **v.metrics},
                ReliabilityClass.PIPELINE_DERIVED, _tool("vetting-v1", res.version), [pa])


def add_quality_evidence(rec: EvidenceRecorder, dq: DataQuality, parents: list[UUID]) -> None:
    p = rec.derived("data_quality", "grade:tce", parents)
    direction = Direction.INCONCLUSIVE if dq.grade.value == "D" else Direction.NEUTRAL
    rec.add("quality", EvidenceChannel.DATA_QUALITY, direction,
            f"Data quality grade {dq.grade.value}" + (f" ({'; '.join(dq.reasons)})" if dq.reasons
                                                       else ""),
            {"grade": dq.grade.value, "reasons": dq.reasons}, ReliabilityClass.PIPELINE_DERIVED,
            _tool("quality-grader", "tq@1"), [p])


def add_model_evidence(rec: EvidenceRecorder, system: TrainedSystem, s: Scored, i: int,
                       parents: list[UUID]) -> None:
    p = rec.derived("prediction", "infer:" + "+".join(m.version for m in system.members), parents)
    label = s.set_labels[i]
    prob, lo, hi = float(s.prob[i]), float(s.lo90[i]), float(s.hi90[i])
    ood, dis = bool(s.ood_flag[i]), bool(s.disagree[i])
    if dis or ood or label in ("uncertain", "abstain"):
        d = Direction.INCONCLUSIVE
    else:
        d = Direction.SUPPORTS if label == "planet_like" else Direction.CONTRADICTS
    notes = (["models disagree"] if dis else []) + (["out-of-distribution"] if ood else [])
    spread = (f"ensemble spread {lo:.2f}-{hi:.2f}" if s.spread_defined
              else "no ensemble spread: single model")
    rec.add("model", EvidenceChannel.MODEL_PREDICTION, d,
            f"Classifier planet-likeness {prob:.2f} ({spread}); "
            f"conformal set: {label}" + (f"; {', '.join(notes)}" if notes else ""),
            {"probability": prob, "conformal_set": label, "ood_flag": ood,
             "ood_percentile": float(s.ood_percentile[i]), "disagree": dis,
             "family_probs": {k: float(v[i]) for k, v in s.family_probs.items()},
             "threshold": system.threshold, "calibration": system.calibrator.method},
            ReliabilityClass.MODEL_OUTPUT,
            Creator(type=CreatorType.MODEL, name="transit-council",
                    version="+".join(m.version for m in system.members)), [p],
            uncertainty={"interval_90": [lo, hi], "spread_defined": s.spread_defined,
                         "kind": "ensemble spread (model uncertainty), not a label interval"
                                 if s.spread_defined else "undefined for a single model; the "
                                 "vacuous [0, 1] interval means 'unknown'"})


def add_anomaly_evidence(rec: EvidenceRecorder, a: AnomalyResult, parents: list[UUID]) -> None:
    p = rec.derived("anomaly", f"anomaly:{a.reference_id}", parents)
    if a.status == AnomalyStatus.INSUFFICIENT_DATA:
        d, claim = Direction.INCONCLUSIVE, a.interpretation()
    else:
        suspect = a.status == AnomalyStatus.ARTIFACT_SUSPECT
        d = Direction.CONTRADICTS if suspect else Direction.NEUTRAL
        claim = a.interpretation()
    rec.add("anomaly", EvidenceChannel.ANOMALY, d, claim,
            {"status": a.status.value, "percentile": a.percentile, "severity": a.severity,
             "category": a.category, "reference": a.reference_id,
             "drivers": a.drivers[:3], "detectors": a.detector_percentiles,
             "artifact_reasons": a.artifact_reasons},
            ReliabilityClass.MODEL_OUTPUT,
            Creator(type=CreatorType.MODEL, name="anomaly-engine", version=a.reference_id), [p])


def add_catalog_evidence(rec: EvidenceRecorder, records: list[CatalogRecord],
                         match: CatalogMatch | None, lookup_source: str, source_uri: str,
                         queries: list[str], period_d: float) -> None:
    creator = _tool("catalog-lookup", __version__)
    if not records:
        p = rec.root("catalog_query", f"query:{lookup_source}", source_uri,
                     {"queries": queries, "rows": 0})
        rec.add("catalog:none", EvidenceChannel.CATALOG_STATUS, Direction.NEUTRAL,
                f"{lookup_source} has no entries for this star",
                {"source": lookup_source, "status": "none", "n_rows": 0},
                ReliabilityClass.ARCHIVE_CURATED, creator, [p])
        return
    for r in records:
        matched = match is not None and match.record is r
        status = r.status or "unclassified"
        if matched:
            d = Direction.CONTRADICTS if status == "false_positive" else Direction.SUPPORTS
            claim = (f"{r.source} {r.table} {r.native_id}: {status}, period "
                     f"{match.catalog_period_d:.4f} d matches this signal ({match.relation}, "  # type: ignore[union-attr]
                     f"{match.rel_diff:.2%} apart)")  # type: ignore[union-attr]
        else:
            d = Direction.NEUTRAL
            cp = record_period(r)
            claim = (f"{r.source} {r.table} {r.native_id}: {status}"
                     + (f", period {cp:.4f} d (does not match this signal)" if cp else ""))
        key = "catalog:match" if matched else f"catalog:{r.table}:{r.native_id}"
        rec.add(key, EvidenceChannel.CATALOG_STATUS, d, claim,
                {"source": r.source, "table": r.table, "native_id": r.native_id, "status": status,
                 "catalog_period_d": record_period(r), "matched": matched,
                 "signal_period_d": period_d,
                 "relation": match.relation if matched and match else None},
                ReliabilityClass.ARCHIVE_CURATED, creator, [rec.catalog_prov(r)])
    if match is None:  # entries exist but none is this signal: that absence is a finding too
        rec.add("catalog:summary", EvidenceChannel.CATALOG_STATUS, Direction.NEUTRAL,
                f"{lookup_source} lists {len(records)} entr{'y' if len(records) == 1 else 'ies'} "
                f"for this star; none matches P={period_d:.4f} d",
                {"source": lookup_source, "status": "none_matching", "n_rows": len(records),
                 "signal_period_d": period_d},
                ReliabilityClass.ARCHIVE_CURATED, creator,
                [rec.catalog_prov(r) for r in records])


def _fmt(v: float | None, nd: int, unit: str) -> str:
    return "unavailable" if v is None else f"{v:.{nd}f}{unit}"


def add_stellar_evidence(rec: EvidenceRecorder, prof: StellarProfile,
                         cont: ContaminationAssessment | None) -> None:
    creator = _tool("gaia-enrichment", "gaia-dr3")
    if prof.star_record is not None:
        sp = rec.catalog_prov(prof.star_record)
        rec.add("gaia:params", EvidenceChannel.CROSS_SURVEY, Direction.NEUTRAL,
                f"Gaia DR3 {prof.source_id}: Teff={_fmt(prof.teff, 0, ' K')}, "
                f"R={_fmt(prof.radius_rsun, 2, ' Rsun')}, logg={_fmt(prof.logg, 2, ' (cgs)')}, "
                f"G={_fmt(prof.g_mag, 2, ' mag')}",
                {"source": "Gaia DR3", "teff": prof.teff, "radius_rsun": prof.radius_rsun,
                 "logg": prof.logg, "g_mag": prof.g_mag}, ReliabilityClass.ARCHIVE_CURATED,
                creator, [sp])
        b = prof.binarity_suspect
        rec.add("gaia:ruwe", EvidenceChannel.CROSS_SURVEY,
                Direction.INCONCLUSIVE if b is None else
                (Direction.CONTRADICTS if b else Direction.SUPPORTS),
                "Gaia RUWE unavailable" if b is None else
                f"Gaia RUWE {prof.ruwe:.2f} ({'above' if b else 'below'} the 1.4 "
                "unresolved-companion indicator)",
                {"source": "Gaia DR3", "ruwe": prof.ruwe, "threshold": 1.4},
                ReliabilityClass.ARCHIVE_CURATED, creator, [sp])
    if cont is not None and prof.cone_record is not None:
        cp = rec.catalog_prov(prof.cone_record)
        if cont.capable:
            d, claim = Direction.CONTRADICTS, (
                f"{len(cont.capable)} Gaia neighbour(s) within {cont.aperture_arcsec:.0f}\" "
                f"could produce a {cont.depth_frac * 1e6:.0f} ppm dip if they eclipsed "
                f"(nearest: {min(n.sep_arcsec for n in cont.capable):.1f}\")")
        elif cont.n_unknown_mag:
            d, claim = Direction.INCONCLUSIVE, (
                f"{cont.n_unknown_mag} neighbour(s) lack a Gaia magnitude; contamination "
                "cannot be fully assessed")
        else:
            ap, dep = f"{cont.aperture_arcsec:.0f}\"", f"{cont.depth_frac * 1e6:.0f} ppm"
            claim = (f"No Gaia neighbours within {ap}: nothing nearby could produce a {dep} dip"
                     if cont.n_in_aperture == 0 else
                     f"None of the {cont.n_in_aperture} Gaia neighbour(s) within {ap} is bright "
                     f"enough to produce a {dep} dip")
            d = Direction.SUPPORTS
        rec.add("gaia:contamination", EvidenceChannel.CROSS_SURVEY, d, claim,
                {"source": "Gaia DR3", "verdict": cont.verdict, "n_capable": len(cont.capable),
                 "n_in_aperture": cont.n_in_aperture, "n_unknown_mag": cont.n_unknown_mag,
                 "capable": [{"source_id": n.source_id, "sep_arcsec": n.sep_arcsec,
                              "delta_g": n.delta_g} for n in cont.capable[:5]],
                 "approximation": "full neighbour flux assumed in aperture; Gaia G proxies band"},
                ReliabilityClass.PIPELINE_DERIVED, creator, [cp])
