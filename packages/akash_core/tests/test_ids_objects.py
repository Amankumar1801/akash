import pytest
from akash_core.ids import canonical_json, job_key, new_id, params_hash, sha256_bytes
from akash_core.schemas import AstronomicalObject, ObjectAlias, ProvenanceRecord
from pydantic import ValidationError


def test_canonical_json_order_independent():
    assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})
    assert params_hash({"a": 1, "b": 2}) == params_hash({"b": 2, "a": 1})


def test_sha256_known_value():
    assert sha256_bytes(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_job_key_idempotent_and_sensitive():
    o = new_id()
    assert job_key(o, "1", {"x": 1}) == job_key(o, "1", {"x": 1})
    assert job_key(o, "1", {"x": 1}) != job_key(o, "2", {"x": 1})
    assert job_key(o, "1", {"x": 1}) != job_key(o, "1", {"x": 2})


def test_object_alias_lookup_and_namespace_normalised():
    obj = AstronomicalObject(
        ra_deg=301.5,
        dec_deg=44.4,
        canonical_name="KIC 8462852",
        aliases=[ObjectAlias(namespace=" kic ", identifier="8462852", source="simbad")],
    )
    assert obj.alias("KIC") == "8462852"
    assert obj.alias("TIC") is None


def test_coordinate_bounds():
    with pytest.raises(ValidationError):
        AstronomicalObject(ra_deg=400, dec_deg=0, canonical_name="x")
    with pytest.raises(ValidationError):
        AstronomicalObject(ra_deg=10, dec_deg=95, canonical_name="x")


def test_provenance_record_is_frozen():
    p = ProvenanceRecord(entity_type="raw_fits", activity="fetch:mast", code_version="0.0.1")
    with pytest.raises(ValidationError):
        p.activity = "other"
