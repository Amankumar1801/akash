import pytest
from akash_core.enums import CreatorType, Direction, EvidenceChannel, ReliabilityClass
from akash_core.ids import new_id
from akash_core.schemas import Creator, Evidence
from pydantic import ValidationError

TOOL = Creator(type=CreatorType.TOOL, name="bls", version="0.1")
LLM = Creator(type=CreatorType.LLM, name="narrator", version="x")


def make(**kw):
    base = dict(
        investigation_id=new_id(),
        channel=EvidenceChannel.OBSERVED_FACT,
        direction=Direction.SUPPORTS,
        claim="Depth is 1820 ppm",
        provenance_ids=(new_id(),),
        created_by=TOOL,
    )
    base.update(kw)
    return Evidence(**base)


def test_valid_evidence():
    assert make().claim.startswith("Depth")


def test_non_interpretation_requires_provenance():
    with pytest.raises(ValidationError):
        make(provenance_ids=())


def test_interpretation_must_be_llm_or_human():
    with pytest.raises(ValidationError):
        make(channel=EvidenceChannel.INTERPRETATION, provenance_ids=(), value={"cites": ["E1"]})


def test_interpretation_must_cite():
    with pytest.raises(ValidationError):
        make(
            channel=EvidenceChannel.INTERPRETATION,
            provenance_ids=(),
            created_by=LLM,
            reliability=ReliabilityClass.LLM_GENERATED,
        )


def test_valid_llm_interpretation():
    e = make(
        channel=EvidenceChannel.INTERPRETATION,
        provenance_ids=(),
        created_by=LLM,
        reliability=ReliabilityClass.LLM_GENERATED,
        value={"cites": ["E1"]},
    )
    assert e.channel == EvidenceChannel.INTERPRETATION


def test_llm_cannot_claim_archive_reliability():
    with pytest.raises(ValidationError):
        make(created_by=LLM, reliability=ReliabilityClass.ARCHIVE_CURATED)


def test_catalog_status_requires_source():
    with pytest.raises(ValidationError):
        make(channel=EvidenceChannel.CATALOG_STATUS)


def test_evidence_is_immutable():
    e = make()
    with pytest.raises(ValidationError):
        e.claim = "changed"
