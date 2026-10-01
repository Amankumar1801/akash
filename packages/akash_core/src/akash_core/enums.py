from enum import StrEnum


class EvidenceChannel(StrEnum):
    """Epistemic type of a finding. Kept separate on purpose; never averaged."""

    OBSERVED_FACT = "observed_fact"
    CATALOG_STATUS = "catalog_status"
    MODEL_PREDICTION = "model_prediction"
    ANOMALY = "anomaly"
    DATA_QUALITY = "data_quality"
    CROSS_SURVEY = "cross_survey"
    INTERPRETATION = "interpretation"


class Direction(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    NEUTRAL = "neutral"
    INCONCLUSIVE = "inconclusive"


class ReliabilityClass(StrEnum):
    """How much the source of a finding should be trusted, qualitatively."""

    ARCHIVE_CURATED = "archive_curated"  # e.g. NASA Exoplanet Archive dispositions
    PIPELINE_DERIVED = "pipeline_derived"  # deterministic AKASH computation
    MODEL_OUTPUT = "model_output"
    LLM_GENERATED = "llm_generated"
    HUMAN_REVIEWED = "human_reviewed"
    UNKNOWN = "unknown"


class CreatorType(StrEnum):
    TOOL = "tool"
    MODEL = "model"
    HUMAN = "human"
    LLM = "llm"


class TriageCategory(StrEnum):
    """Fixed vocabulary. 'Discovery' is deliberately absent."""

    KNOWN_CONFIRMED = "known_confirmed"
    KNOWN_CANDIDATE = "known_candidate"
    KNOWN_FALSE_POSITIVE = "known_false_positive"
    NEW_SIGNAL_REVIEW = "new_signal_review"
    LIKELY_SYSTEMATIC = "likely_systematic"
    MODELS_DISAGREE = "models_disagree"
    INSUFFICIENT_DATA = "insufficient_data"


class VetStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    UNKNOWN = "unknown"


class QualityGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class Modality(StrEnum):
    LIGHT_CURVE = "light_curve"
    SPECTRUM = "spectrum"
    IMAGE = "image"
    CATALOG_ROW = "catalog_row"


class ProvRelation(StrEnum):
    """Subset of W3C PROV relations."""

    USED = "used"
    WAS_GENERATED_BY = "wasGeneratedBy"
    WAS_DERIVED_FROM = "wasDerivedFrom"
