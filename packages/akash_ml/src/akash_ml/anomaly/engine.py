"""AnomalyEngine: quality gate -> artifact screen -> calibrated ensemble score -> drivers.

WORDING CONTRACT: a high percentile means "unusual relative to <reference population>; requires
investigation". It never means "discovery" or "new object". Artifact-suspect objects are scored
but excluded from review priority, with the reasons attached."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
from akash_core.enums import QualityGrade
from akash_core.schemas import Anomaly, DataQuality
from akash_data.lightcurve import NormalizedLightCurve
from akash_science.lightcurve.variability import (
    FEATURE_NAMES,
    UnusableLightCurve,
    VariabilityResult,
    assess_artifacts,
    extract_variability,
)

from ..transit.explain import bins_to_windows
from ..uncertainty.quality import grade_lightcurve_quality
from .categorize import categorize
from .reference import ReferencePopulation

TOP_DRIVERS = 5


class AnomalyStatus(StrEnum):
    SCORED = "scored"
    ARTIFACT_SUSPECT = "artifact_suspect"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass
class AnomalyResult:
    status: AnomalyStatus
    reference_id: str
    data_quality: DataQuality
    percentile: float | None = None  # vs held-out reference; None if not scored
    severity: float | None = None  # continuous tail distance; used for ranking (percentile ties)
    detector_percentiles: dict[str, float] = field(default_factory=dict)
    category: str | None = None
    drivers: list[dict[str, float | str]] = field(default_factory=list)
    artifact_reasons: list[str] = field(default_factory=list)
    # AE-localised regions as (start, end, weight) in fractions of the baseline
    unusual_regions: list[tuple[float, float, float]] = field(default_factory=list)
    note: str = ""

    @property
    def review_priority(self) -> float | None:
        """Rank key for the review queue: only genuinely scored, non-artifact objects."""
        return self.severity if self.status == AnomalyStatus.SCORED else None

    def interpretation(self) -> str:
        if self.status == AnomalyStatus.INSUFFICIENT_DATA:
            return f"Not scored: {self.note}"
        base = (f"Unusual relative to {self.reference_id} (percentile {self.percentile:.1f}); "
                "requires investigation. This is an anomaly score, not a discovery claim.")
        if self.status == AnomalyStatus.ARTIFACT_SUSPECT:
            return base + " Instrumental artifact suspected: " + "; ".join(self.artifact_reasons)
        return base

    def to_core(self) -> Anomaly | None:
        if self.percentile is None or self.category is None:
            return None
        return Anomaly(percentile=float(self.percentile), reference_population=self.reference_id,
                       category=self.category, drivers=list(self.drivers))


class AnomalyEngine:
    def __init__(self, reference: ReferencePopulation) -> None:
        self.ref = reference

    def analyze(self, lc: NormalizedLightCurve) -> AnomalyResult:
        try:
            vr = extract_variability(lc)
        except UnusableLightCurve as e:
            return AnomalyResult(
                AnomalyStatus.INSUFFICIENT_DATA, self.ref.ref_id,
                DataQuality(grade=QualityGrade.D, reasons=[str(e)]), note=str(e))
        return self.analyze_extracted(vr)

    def analyze_extracted(self, vr: VariabilityResult) -> AnomalyResult:
        dq = grade_lightcurve_quality(vr.quality)
        if dq.grade == QualityGrade.D:
            return AnomalyResult(AnomalyStatus.INSUFFICIENT_DATA, self.ref.ref_id, dq,
                                 note="; ".join(dq.reasons) or "data quality too low")
        s = self.ref.score(vr.features, vr.representation)
        pct = float(s.percentile[0])
        z = self.ref.driver_z(vr.features)
        order = np.argsort(-np.abs(z))[:TOP_DRIVERS]
        drivers: list[dict[str, float | str]] = [
            {"feature": FEATURE_NAMES[i], "robust_z": float(z[i])} for i in order]
        suspect, reasons = assess_artifacts(vr.artifact, self.ref.artifact_thresholds)
        cat = "artifact_suspect" if suspect else categorize(
            [(FEATURE_NAMES[i], float(z[i])) for i in order])
        regions: list[tuple[float, float, float]] = []
        if self.ref.use_ae:
            res = self.ref.localize(vr.representation)[0]
            regions = bins_to_windows(res, np.linspace(0, 1, len(res)), k=3, min_frac=0.4)
        return AnomalyResult(
            AnomalyStatus.ARTIFACT_SUSPECT if suspect else AnomalyStatus.SCORED,
            self.ref.ref_id, dq, pct, float(s.severity[0]),
            {k: float(v[0]) for k, v in s.percentiles.items()}, cat, drivers, reasons, regions)
