"""Rule-based triage. Deterministic, ordered, first-match-wins; every decision carries reasons
that point at evidence rows. No score, no weights.

Why rules, not a learned or Bayesian combiner: there are no ground-truth outcomes to learn from
and any prior would be an invented number. Rules are auditable and each one can be argued with.

PRECEDENCE (and why):
 1 known catalog match   - an external, curated fact beats our own inference; we REPORT it.
 2 insufficient data     - without usable data nothing below means anything.
 3 hard vetting failure  - deterministic measurements beat model opinion.
 4 corroborated artifact - two independent systematics indicators.
 5 several vetting warns - heuristic count (TriageConfig.n_warn_decisive); tunable, to be
                           measured in Phase 10.
 6 models disagree       - disagreement is information; send it to a human.
 7 classifier says no    - a MODEL prediction, labelled as such in the reason.
 8 otherwise             - new signal needing review.

NAMING NOTE: the closed enum's LIKELY_SYSTEMATIC covers any failed-vetting signature, including
astrophysical false positives such as eclipsing binaries; the reason text names the mechanism.
Renaming the enum value needs an ADR (it is a core contract)."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from akash_core.enums import QualityGrade, TriageCategory, VetStatus

from .catalog_match import CatalogMatch
from .stellar import ContaminationAssessment

_KNOWN = {"confirmed": TriageCategory.KNOWN_CONFIRMED, "candidate": TriageCategory.KNOWN_CANDIDATE,
          "false_positive": TriageCategory.KNOWN_FALSE_POSITIVE}


@dataclass(frozen=True)
class TriageConfig:
    hard_fail_checks: tuple[str, ...] = ("odd_even", "secondary_eclipse", "duration_plausibility")
    warn_count_checks: tuple[str, ...] = ("odd_even", "secondary_eclipse", "transit_shape",
                                          "implied_radius", "systematics_coincidence")
    n_warn_decisive: int = 2
    min_transits: int = 2


@dataclass
class ModelView:
    probability: float
    set_label: str
    ood_flag: bool
    disagree: bool
    evidence_id: UUID


@dataclass
class TriageInputs:
    quality_grade: QualityGrade
    quality_evidence: UUID
    n_transits: int
    signal_evidence: UUID
    vetting: dict[str, VetStatus]
    vetting_evidence: dict[str, UUID]
    catalog_match: CatalogMatch | None = None
    catalog_evidence: UUID | None = None  # matched row, or the 'no entries' row
    catalog_available: bool = True
    star_has_other_entries: bool = False
    model: ModelView | None = None
    anomaly_artifact_suspect: bool = False
    anomaly_evidence: UUID | None = None
    contamination: ContaminationAssessment | None = None
    contamination_evidence: UUID | None = None
    binarity_suspect: bool | None = None
    binarity_evidence: UUID | None = None


@dataclass
class Reason:
    rule: str
    evidence_ids: list[UUID]
    text: str


@dataclass
class TriageDecision:
    category: TriageCategory
    reasons: list[Reason]
    followups: list[str] = field(default_factory=list)


def triage(x: TriageInputs, cfg: TriageConfig | None = None) -> TriageDecision:
    cfg = cfg or TriageConfig()
    v = x.vetting
    followups = _followups(x)

    if x.catalog_match is not None and x.catalog_evidence is not None:
        m = x.catalog_match
        return TriageDecision(
            _KNOWN[m.status],
            [Reason(f"catalog_period_match:{m.relation}", [x.catalog_evidence],
                    f"Period matches {m.record.source} {m.record.table} {m.record.native_id} "
                    f"({m.status}); status is reported from the catalog, not decided by AKASH")],
            followups)

    if x.quality_grade == QualityGrade.D or x.n_transits < cfg.min_transits:
        why = ("data quality grade D" if x.quality_grade == QualityGrade.D
               else f"only {x.n_transits} transit(s): periodicity unverified")
        return TriageDecision(TriageCategory.INSUFFICIENT_DATA,
                              [Reason("insufficient_data", [x.quality_evidence, x.signal_evidence],
                                      why)], followups)

    hard = [c for c in cfg.hard_fail_checks if v.get(c) == VetStatus.FAIL]
    if hard:
        return TriageDecision(TriageCategory.LIKELY_SYSTEMATIC,
                              [Reason(f"vetting_fail:{c}", [x.vetting_evidence[c]],
                                      f"{c} check failed") for c in hard], followups)

    if v.get("systematics_coincidence") == VetStatus.WARN and x.anomaly_artifact_suspect \
            and x.anomaly_evidence is not None:
        return TriageDecision(
            TriageCategory.LIKELY_SYSTEMATIC,
            [Reason("systematics_corroborated",
                    [x.vetting_evidence["systematics_coincidence"], x.anomaly_evidence],
                    "transits coincide with flagged cadences/edges AND the light curve shows "
                    "instrumental-artifact signatures")], followups)

    warns = [c for c in cfg.warn_count_checks if v.get(c) in (VetStatus.WARN, VetStatus.FAIL)]
    if len(warns) >= cfg.n_warn_decisive:
        return TriageDecision(
            TriageCategory.LIKELY_SYSTEMATIC,
            [Reason(f"vetting_warn:{c}", [x.vetting_evidence[c]], f"{c} flagged a concern")
             for c in warns], followups)

    if x.model is not None and x.model.disagree:
        return TriageDecision(
            TriageCategory.MODELS_DISAGREE,
            [Reason("models_disagree", [x.model.evidence_id],
                    "independent model families disagree; manual investigation recommended")],
            followups)

    if x.model is not None and x.model.set_label == "not_planet_like" and not x.model.ood_flag:
        return TriageDecision(
            TriageCategory.LIKELY_SYSTEMATIC,
            [Reason("classifier_not_planet_like", [x.model.evidence_id],
                    "MODEL PREDICTION (not a measurement): the classifier's conformal set "
                    "excludes planet-like")], followups)

    reasons: list[Reason] = []
    if x.catalog_evidence is not None:
        reasons.append(Reason(
            "no_catalog_match" if x.catalog_available else "catalog_unavailable",
            [x.catalog_evidence],
            ("no catalog entry matches this period" +
             ("; the star hosts other catalog entries" if x.star_has_other_entries else ""))
            if x.catalog_available else "catalog lookup unavailable: novelty is UNVERIFIED"))
    passed = [c for c, s in v.items() if s == VetStatus.PASS]
    if passed:
        reasons.append(Reason("vetting_no_decisive_failure",
                              [x.vetting_evidence[c] for c in passed],
                              f"{len(passed)} vetting checks passed; none decisive against"))
    if x.model is not None:
        reasons.append(Reason("model_not_excluding", [x.model.evidence_id],
                              f"classifier set '{x.model.set_label}' does not exclude planet-like"))
    if not reasons:
        reasons.append(Reason("signal_detected", [x.signal_evidence],
                              "a periodic signal was detected and nothing decisive argues "
                              "against it"))
    return TriageDecision(TriageCategory.NEW_SIGNAL_REVIEW, reasons, followups)


_CHECK_FOLLOWUP = {
    "odd_even": "Compare odd/even transit depths with more transits (eclipsing binary at twice "
                "this period?)",
    "secondary_eclipse": "Inspect phase 0.5 for a secondary eclipse (eclipsing-binary scenario)",
    "transit_shape": "Fit a limb-darkened transit model; check a grazing-binary scenario",
    "implied_radius": "Implied radius is large: consider a stellar companion; check the stellar "
                      "radius",
    "periodicity_coverage": "Individual transit depths are inconsistent: check for blended "
                            "events or systematics",
    "systematics_coincidence": "Check whether transits coincide with momentum dumps, scattered "
                               "light or segment edges",
    "duration_plausibility": "Transit duration is implausible for this star: re-check stellar "
                             "parameters or consider an eclipsing/different-host scenario",
}


def _followups(x: TriageInputs) -> list[str]:
    """Every WARN/FAIL vetting result yields an action, so a concern is never left without a
    next step; checks are listed in a stable order."""
    out: list[str] = []
    v = x.vetting
    if x.n_transits < 4 or v.get("odd_even") == VetStatus.UNKNOWN:
        out.append("Observe additional transits/sectors to verify periodicity and odd/even depths")
    for name, text in _CHECK_FOLLOWUP.items():
        if v.get(name) in (VetStatus.WARN, VetStatus.FAIL) and text not in out:
            out.append(text)
    if x.contamination is not None and x.contamination.capable:
        out.append("Check centroid motion / difference imaging; consider statistical validation "
                   "(e.g. TRICERATOPS) for the nearby-source scenario")
    if x.binarity_suspect:
        out.append("High-resolution imaging for an unresolved companion (elevated Gaia RUWE)")
    if x.model is not None and x.model.ood_flag:
        out.append("Classifier inputs are out-of-distribution: rely on vetting and manual review")
    if x.model is not None and x.model.disagree:
        out.append("Models disagree: manual investigation recommended")
    if not x.catalog_available:
        out.append("Catalog lookup was unavailable: re-check TOI/KOI/Exoplanet Archive status")
    if x.quality_grade in (QualityGrade.C, QualityGrade.D):
        out.append("Data quality is low: seek cleaner photometry before drawing conclusions")
    return out
