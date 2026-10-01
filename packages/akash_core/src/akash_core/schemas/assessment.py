from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from akash_core.enums import QualityGrade, TriageCategory, VetStatus


class _Strict(BaseModel):
    # extra="forbid" is load-bearing: it blocks anyone adding a combined "score" field.
    model_config = ConfigDict(extra="forbid")


class Interval(_Strict):
    value: float
    lo: float
    hi: float

    @model_validator(mode="after")
    def _ordered(self) -> Interval:
        if not (self.lo <= self.value <= self.hi):
            raise ValueError("interval must satisfy lo <= value <= hi")
        return self


class TransitSummary(_Strict):
    period_d: Interval
    depth_ppm: float = Field(ge=0)
    duration_h: float = Field(gt=0)
    snr: float
    n_transits: int = Field(ge=0)


class Disagreement(_Strict):
    flag: bool
    range: float = Field(ge=0.0, le=1.0)


class Prediction(_Strict):
    planet_like_probability: float = Field(ge=0.0, le=1.0)
    interval_90: tuple[float, float]
    calibrated: bool
    calibration_method: str | None = None
    model_versions: list[str] = Field(min_length=1)
    disagreement: Disagreement | None = None

    @model_validator(mode="after")
    def _interval_ok(self) -> Prediction:
        lo, hi = self.interval_90
        if not (0.0 <= lo <= self.planet_like_probability <= hi <= 1.0):
            raise ValueError("interval_90 must bracket the probability within [0, 1]")
        if self.calibrated and not self.calibration_method:
            raise ValueError("calibrated=True requires calibration_method")
        return self


class Anomaly(_Strict):
    percentile: float = Field(ge=0.0, le=100.0)
    reference_population: str  # percentile is meaningless without this
    category: str
    drivers: list[dict[str, float | str]] = Field(default_factory=list)


class DataQuality(_Strict):
    grade: QualityGrade
    reasons: list[str] = Field(default_factory=list)


class OODInfo(_Strict):
    flag: bool
    distance_percentile: float | None = Field(default=None, ge=0.0, le=100.0)


class KnownStatus(_Strict):
    source: str
    status: str  # "none" | "confirmed" | "candidate" | "false_positive"
    retrieved_at: str


class TriageReason(_Strict):
    rule: str
    evidence_ids: list[UUID] = Field(min_length=1)


class Assessment(_Strict):
    """Per-investigation result. Channels stay separate; there is no aggregate score."""

    investigation_id: UUID
    object_id: UUID
    triage_category: TriageCategory
    triage_reasons: list[TriageReason] = Field(min_length=1)
    transit: TransitSummary | None = None
    prediction: Prediction | None = None
    anomaly: Anomaly | None = None
    data_quality: DataQuality
    ood: OODInfo | None = None
    vetting: dict[str, VetStatus] = Field(default_factory=dict)
    known_status: KnownStatus | None = None
    conflicting_evidence: list[UUID] = Field(default_factory=list)
    recommended_followup: list[str] = Field(default_factory=list)
    disclaimer_version: str = "v1"
