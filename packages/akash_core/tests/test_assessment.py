import pytest
from akash_core.enums import QualityGrade, TriageCategory
from akash_core.ids import new_id
from akash_core.schemas import Assessment, DataQuality, Prediction, TriageReason
from pydantic import ValidationError


def base(**kw):
    d = dict(
        investigation_id=new_id(),
        object_id=new_id(),
        triage_category=TriageCategory.NEW_SIGNAL_REVIEW,
        triage_reasons=[TriageReason(rule="no_catalog_match", evidence_ids=[new_id()])],
        data_quality=DataQuality(grade=QualityGrade.B),
    )
    d.update(kw)
    return Assessment(**d)


def test_assessment_ok():
    assert base().disclaimer_version == "v1"


def test_no_aggregate_score_field_allowed():
    with pytest.raises(ValidationError):
        base(score=0.97)


def test_triage_requires_reasons():
    with pytest.raises(ValidationError):
        base(triage_reasons=[])


def test_no_discovery_category_exists():
    assert "discovery" not in {c.value for c in TriageCategory}


def test_prediction_interval_must_bracket():
    with pytest.raises(ValidationError):
        Prediction(
            planet_like_probability=0.9,
            interval_90=(0.1, 0.5),
            calibrated=False,
            model_versions=["m@1"],
        )


def test_calibrated_requires_method():
    with pytest.raises(ValidationError):
        Prediction(
            planet_like_probability=0.5,
            interval_90=(0.4, 0.6),
            calibrated=True,
            model_versions=["m@1"],
        )
