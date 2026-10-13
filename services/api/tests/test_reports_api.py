import json

from akash_api.auth import ApiKeyStore
from conftest import H, submit, wait_done


def finished(client, keys, who="researcher"):
    inv = submit(client, keys[who], "TIC 1").json()["investigation_id"]
    wait_done(client, H(keys[who]), inv)
    return inv


def rep(client, keys, inv, fmt="json", who="researcher"):
    return client.post("/v1/reports", json={"investigation_id": inv, "format": fmt},
                       headers=H(keys[who]))


def test_json_report_cites_only_this_investigations_evidence(client, keys):
    inv = finished(client, keys)
    r = rep(client, keys, inv)
    assert r.status_code == 200
    body = r.json()
    ev = {e["evidence_id"] for e in client.get(
        f"/v1/investigations/{inv}/evidence", headers=H(keys["researcher"])).json()}
    cited = {i for s in body["sections"] for b in s["blocks"] for i in b["evidence_ids"]}
    assert cited and cited <= ev and {p["evidence_id"] for p in body["provenance"]} == ev
    assert len(body["sections"]) == 13 and body["provenance_verifiable"] is True
    assert body["object_name"] and len(body["content_sha256"]) == 64


def test_same_investigation_gives_same_content_hash(client, keys):
    inv = finished(client, keys)
    assert rep(client, keys, inv).json()["content_sha256"] == \
        rep(client, keys, inv).json()["content_sha256"]


def test_markdown_and_html_downloads(client, keys):
    inv = finished(client, keys)
    md = rep(client, keys, inv, "markdown")
    assert md.headers["content-type"].startswith("text/markdown")
    assert "attachment" in md.headers["content-disposition"] and "## 13." in md.text
    h = rep(client, keys, inv, "html")
    assert h.headers["content-type"].startswith("text/html")
    assert "default-src 'none'" in h.headers["content-security-policy"]
    assert "<script" not in h.text.lower()


def test_private_unfinished_and_bad_requests(client, keys):
    from conftest import GATE
    inv = finished(client, keys)
    assert rep(client, keys, inv, who="researcher2").status_code == 404
    assert rep(client, keys, "00000000-0000-4000-8000-000000000000").status_code == 404
    assert client.post("/v1/reports", json={"investigation_id": inv}).status_code == 401
    for body in ({}, {"investigation_id": "x"}, {"investigation_id": inv, "format": "pdf"},
                 {"investigation_id": inv, "extra": 1}):
        r = client.post("/v1/reports", json=body, headers=H(keys["researcher"]))
        assert r.status_code in (400, 422)
    GATE.clear()
    j = submit(client, keys["researcher"], "TIC 9").json()["investigation_id"]
    assert rep(client, keys, j).status_code == 409
    GATE.set()
    wait_done(client, H(keys["researcher"]), j)


def test_report_is_audited_and_rate_limited(client, services, keys):
    inv = finished(client, keys)
    services.settings.api_report_rate_per_min = 2
    codes = [rep(client, keys, inv).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    with services.context() as ctx:
        acts = [(e["principal"], e["action"]) for e in ApiKeyStore(ctx.conn).audit_entries()]
    assert ("rita", "report.create") in acts
    assert json.dumps(codes)
