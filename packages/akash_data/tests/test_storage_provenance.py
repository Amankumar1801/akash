import pytest
from akash_core.enums import ProvRelation
from akash_core.errors import ValidationFailure
from akash_core.schemas import AstronomicalObject, ObjectAlias, ProvenanceRecord
from akash_data.storage import IntegrityError
from akash_provenance.store import ProvenanceError


def test_put_is_idempotent_and_content_addressed(artifacts):
    a = artifacts.put(b"hello", "raw")
    b = artifacts.put(b"hello", "raw")
    assert a == b and artifacts.get(a.sha256) == b"hello"


def test_tamper_detected(artifacts):
    ref = artifacts.put(b"data", "raw")
    from pathlib import Path
    from urllib.parse import urlparse
    from urllib.request import url2pathname
    # a file URI is file:///C:/dir/x on Windows and file:///dir/x elsewhere; url2pathname handles both
    Path(url2pathname(urlparse(ref.uri).path)).write_bytes(b"corrupt")
    with pytest.raises(IntegrityError):
        artifacts.get(ref.sha256)


def test_quarantine_flag(artifacts):
    ref = artifacts.put(b"x", "raw")
    assert artifacts.is_quarantined(ref.sha256) == (False, None)
    artifacts.quarantine(ref.sha256, "bad")
    assert artifacts.is_quarantined(ref.sha256) == (True, "bad")


def test_alias_unique_across_objects(repo):
    a = AstronomicalObject(ra_deg=1, dec_deg=1, canonical_name="a",
                           aliases=[ObjectAlias(namespace="TIC", identifier="1", source="s")])
    b = AstronomicalObject(ra_deg=2, dec_deg=2, canonical_name="b",
                           aliases=[ObjectAlias(namespace="TIC", identifier="1", source="s")])
    repo.save_object(a)
    with pytest.raises(ValidationFailure):
        repo.save_object(b)
    assert repo.find_by_alias("tic", "1").object_id == a.object_id


def test_lineage_and_verify_chain(prov):
    raw = prov.add(ProvenanceRecord(entity_type="raw", activity="fetch", code_version="1",
                                    sha256="ab", source_uri="http://x"))
    mid = prov.add(ProvenanceRecord(entity_type="clean", activity="clean", code_version="1"))
    top = prov.add(ProvenanceRecord(entity_type="pred", activity="infer", code_version="1"))
    prov.link(mid.prov_id, raw.prov_id, ProvRelation.WAS_DERIVED_FROM)
    prov.link(top.prov_id, mid.prov_id, ProvRelation.WAS_DERIVED_FROM)
    assert {r.prov_id for r in prov.lineage(top.prov_id)} == {raw.prov_id, mid.prov_id}
    prov.verify_chain(top.prov_id)


def test_verify_chain_fails_without_source(prov):
    root = prov.add(ProvenanceRecord(entity_type="raw", activity="fetch", code_version="1"))
    child = prov.add(ProvenanceRecord(entity_type="x", activity="y", code_version="1"))
    prov.link(child.prov_id, root.prov_id, ProvRelation.WAS_DERIVED_FROM)
    with pytest.raises(ProvenanceError):
        prov.verify_chain(child.prov_id)
