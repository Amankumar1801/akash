import hmac
import logging

import numpy as np
import pytest
from akash_api import auth as auth_mod
from akash_api.app import create_app
from akash_api.auth import ApiKeyStore, Role
from akash_core.config import Settings
from conftest import H, add_observation, make_lc
from fastapi.testclient import TestClient

PROTECTED = [("GET", "/v1/me"), ("POST", "/v1/objects/search"), ("GET", f"/v1/objects/{'0' * 8}-0000-0000-0000-{'0' * 12}"),
             ("GET", f"/v1/objects/{'0' * 8}-0000-0000-0000-{'0' * 12}/observations"),
             ("GET", f"/v1/observations/{'0' * 8}-0000-0000-0000-{'0' * 12}/data"),
             ("POST", "/v1/investigations"), ("GET", "/v1/investigations"),
             ("GET", f"/v1/investigations/{'0' * 8}-0000-0000-0000-{'0' * 12}"),
             ("DELETE", f"/v1/investigations/{'0' * 8}-0000-0000-0000-{'0' * 12}"),
             ("GET", f"/v1/investigations/{'0' * 8}-0000-0000-0000-{'0' * 12}/events"),
             ("GET", f"/v1/investigations/{'0' * 8}-0000-0000-0000-{'0' * 12}/log"),
             ("GET", f"/v1/investigations/{'0' * 8}-0000-0000-0000-{'0' * 12}/evidence"),
             ("GET", f"/v1/investigations/{'0' * 8}-0000-0000-0000-{'0' * 12}/provenance"),
             ("GET", "/v1/models"), ("GET", "/v1/models/a/b"),
             ("POST", "/v1/spectra/analyze"), ("POST", "/v1/images/analyze"),
             ("GET", "/v1/discoveries/interpret?nl=x"),
             ("GET", f"/v1/observations/{'0' * 8}-0000-0000-0000-{'0' * 12}/variability")]


# ---------- key handling ----------
def test_database_never_holds_a_usable_credential(services, keys):
    secrets_ = [k.split("_", 2)[2] for k in keys.values()]
    with services.context() as ctx:
        rows = ctx.conn.execute("SELECT key_id, secret_hash, name, role FROM api_key").fetchall()
        dump = " ".join(str(c) for r in rows for c in r)
    assert len(rows) == 4 and all(len(r[1]) == 64 for r in rows)
    assert not any(s in dump for s in secrets_) and not any(k in dump for k in keys.values())


def test_verify_accepts_good_and_rejects_everything_else(services, keys):
    with services.context() as ctx:
        store = ApiKeyStore(ctx.conn)
        p = store.verify(keys["researcher"])
        assert p and p.name == "rita" and p.role == Role.RESEARCHER and p.at_least(Role.VIEWER)
        kid, secret = keys["viewer"].split("_", 2)[1:]
        for bad in (None, "", "akash_", "x_y_z", f"akash_{kid}_wrong", f"akash_ffffffff_{secret}",
                    f"akash_{kid}", "akash_" + "a" * 500, f"bearer {keys['viewer']}"):
            assert store.verify(bad) is None, bad


def test_revoked_keys_stop_working_immediately(client, services, keys):
    assert client.get("/v1/me", headers=H(keys["viewer"])).status_code == 200
    with services.context() as ctx:
        store = ApiKeyStore(ctx.conn)
        assert store.revoke(keys["viewer"].split("_")[1]) and not store.revoke(keys["viewer"].split("_")[1])
    assert client.get("/v1/me", headers=H(keys["viewer"])).status_code == 401


def test_secret_comparison_is_constant_time_even_for_unknown_key_ids(services, keys, monkeypatch):
    calls = []
    real = hmac.compare_digest
    monkeypatch.setattr(auth_mod.hmac, "compare_digest", lambda a, b: (calls.append(1), real(a, b))[1])
    with services.context() as ctx:
        ApiKeyStore(ctx.conn).verify("akash_ffffffff_whatever")  # no such key id
        ApiKeyStore(ctx.conn).verify(keys["viewer"])
    assert len(calls) == 2  # unknown ids are compared too: no early exit to time


def test_unknown_role_is_refused(services):
    with services.context() as ctx, pytest.raises(ValueError):
        ApiKeyStore(ctx.conn).create("eve", "superuser")


# ---------- authentication / authorization at the HTTP layer ----------
def test_health_is_public_and_leaks_nothing_sensitive(client):
    r = client.get("/v1/health")
    assert r.status_code == 200 and "does not independently establish" in r.json()["disclaimer"]
    assert "key" not in r.text.lower()


@pytest.mark.parametrize("method,path", PROTECTED)
def test_every_protected_route_rejects_anonymous_callers(client, method, path):
    r = client.request(method, path)
    assert r.status_code == 401, (method, path)
    assert r.headers["www-authenticate"] == "Bearer"
    err = r.json()["error"]
    assert err["code"] == "unauthenticated" and err["request_id"] == r.headers["x-request-id"]


def test_bearer_and_x_api_key_work_but_query_string_keys_do_not(client, keys):
    assert client.get("/v1/me", headers=H(keys["viewer"])).json()["name"] == "vera"
    assert client.get("/v1/me", headers={"X-API-Key": keys["viewer"]}).status_code == 200
    assert client.get(f"/v1/me?api_key={keys['viewer']}").status_code == 401
    assert client.get("/v1/me", headers={"Authorization": f"Basic {keys['viewer']}"}).status_code == 401


def test_roles_are_enforced_and_authorization_precedes_validation(client, keys):
    me = {r: client.get("/v1/me", headers=H(keys[r])).json() for r in ("viewer", "researcher", "admin")}
    assert [me[r]["role"] for r in ("viewer", "researcher", "admin")] == ["viewer", "researcher", "admin"]
    # a viewer cannot learn anything about the request schema: 403 comes before 422
    r = client.post("/v1/investigations", json={}, headers=H(keys["viewer"]))
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert client.post("/v1/investigations", json={}, headers=H(keys["researcher"])).status_code == 422
    assert client.delete(f"/v1/investigations/{'0' * 8}-0000-0000-0000-{'0' * 12}",
                         headers=H(keys["viewer"])).status_code == 403


def test_denials_are_audited_without_credentials(client, services, keys):
    client.get("/v1/me", headers=H("akash_deadbeef_notarealsecretvalue"))
    client.post("/v1/investigations", json={}, headers=H(keys["viewer"]))
    with services.context() as ctx:
        entries = ApiKeyStore(ctx.conn).audit_entries()
    outcomes = {(e["principal"], e["outcome"]) for e in entries}
    assert (None, "denied:bad_credentials") in outcomes and ("vera", "denied:needs_researcher") in outcomes
    blob = repr(entries)
    assert "notarealsecretvalue" not in blob and keys["viewer"] not in blob
    assert all(e["request_id"] for e in entries)


def test_access_log_never_contains_credentials_or_query_strings(client, keys, caplog):
    with caplog.at_level(logging.INFO, logger="akash.access"):
        client.get("/v1/me?token=SECRETQUERY", headers=H(keys["viewer"]))
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "/v1/me" in text and '"principal": "vera"' in text
    assert keys["viewer"] not in text and "SECRETQUERY" not in text and "Bearer" not in text


# ---------- request ids, headers, envelopes ----------
def test_request_ids_are_echoed_only_when_safe(client):
    ok = client.get("/v1/health", headers={"X-Request-ID": "trace-abc_12345"})
    assert ok.headers["x-request-id"] == "trace-abc_12345"
    for evil in ("a b c d e f g h", "x" * 200, "id\r\nSet-Cookie: s=1", "short"):
        got = client.get("/v1/health", headers={"X-Request-ID": evil.replace("\r\n", "")}).headers["x-request-id"]
        assert got != evil and len(got) == 32 and "\n" not in got


def test_security_headers_on_success_and_error(client):
    for r in (client.get("/v1/health"), client.get("/v1/me")):
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["cache-control"] == "no-store" and r.headers["referrer-policy"] == "no-referrer"


def test_unknown_routes_and_methods_use_the_envelope(client):
    r = client.get("/v1/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = client.put("/v1/health")
    assert r.status_code == 405 and r.json()["error"]["code"] == "method_not_allowed"


def test_validation_errors_never_echo_submitted_values(client, keys):
    r = client.post("/v1/objects/search", headers=H(keys["viewer"]),
                    json={"query": "x" * 500, "token": "SUPER-SECRET-VALUE"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"
    assert "SUPER-SECRET-VALUE" not in r.text and "x" * 50 not in r.text
    assert r.json()["error"]["problems"]


def test_oversized_bodies_are_rejected(services, settings, keys):
    small = settings.model_copy(update={"api_max_body_bytes": 200})
    with TestClient(create_app(small, services)) as c:
        r = c.post("/v1/objects/search", headers=H(keys["viewer"]), json={"query": "x" * 1000})
        assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"
        chunks = (b"x" * 100 for _ in range(10))  # no Content-Length: counted as it streams
        r2 = c.post("/v1/objects/search", headers=H(keys["viewer"]), content=chunks)
        assert r2.status_code == 413


def test_docs_and_cors_are_off_by_default(client, services, settings, keys):
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404
    r = client.get("/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers
    dev = settings.model_copy(update={"env": "dev", "api_cors_origins": "https://app.example"})
    with TestClient(create_app(dev, services)) as c:
        assert c.get("/docs").status_code == 200
        ok = c.get("/v1/health", headers={"Origin": "https://app.example"})
        bad = c.get("/v1/health", headers={"Origin": "https://evil.example"})
        assert ok.headers["access-control-allow-origin"] == "https://app.example"
        assert "access-control-allow-origin" not in bad.headers


def test_unconfigured_deployment_fails_loudly_but_health_still_answers(settings):
    with TestClient(create_app(settings, None)) as c:
        assert c.get("/v1/health").status_code == 200
        r = c.get("/v1/me", headers={"Authorization": "Bearer akash_x_y"})
        assert r.status_code == 503 and r.json()["error"]["code"] == "service_unavailable"


# ---------- rate limiting over HTTP ----------
def test_rate_limit_returns_429_with_retry_after_and_is_per_principal(services, settings, keys):
    tight = settings.model_copy(update={"api_rate_per_min": 3})
    services.settings = tight
    with TestClient(create_app(tight, services)) as c:
        codes = [c.get("/v1/me", headers=H(keys["viewer"])).status_code for _ in range(5)]
        assert codes == [200, 200, 200, 429, 429]
        r = c.get("/v1/me", headers=H(keys["viewer"]))
        assert int(r.headers["retry-after"]) >= 1 and r.json()["error"]["code"] == "rate_limited"
        assert c.get("/v1/me", headers=H(keys["admin"])).status_code == 200  # someone else
        assert c.get("/v1/health").status_code == 200  # public routes are never limited


def test_expensive_endpoint_has_its_own_tighter_bucket(services, settings, keys):
    tight = settings.model_copy(update={"api_investigation_rate_per_min": 2})
    services.settings = tight
    with TestClient(create_app(tight, services)) as c:
        codes = [c.post("/v1/investigations", json={}, headers=H(keys["researcher"])).status_code
                 for _ in range(4)]
        assert codes == [422, 422, 429, 429]
        assert c.get("/v1/me", headers=H(keys["researcher"])).status_code == 200  # general bucket


# ---------- objects & observations (also exercises error mapping) ----------
def test_search_resolves_and_is_idempotent(client, keys):
    a = client.post("/v1/objects/search", json={"query": "TIC 1"}, headers=H(keys["viewer"]))
    b = client.post("/v1/objects/search", json={"query": "TIC 1"}, headers=H(keys["viewer"]))
    assert a.status_code == 200 and a.json()["object_id"] == b.json()["object_id"]
    body = a.json()
    assert body["canonical_name"] == "TIC 1" and {"namespace": "TIC", "identifier": "1"} in body["aliases"]
    assert client.get(f"/v1/objects/{body['object_id']}", headers=H(keys["viewer"])).json() == body


@pytest.mark.parametrize("query,status,code", [
    ("nonsense", 404, "object_not_found"), ("AMBIG", 409, "ambiguous_identity"),
    ("BAD", 422, "validation_failed"), ("DOWN", 502, "upstream_error")])
def test_resolver_failures_map_to_precise_http_errors(client, keys, query, status, code):
    r = client.post("/v1/objects/search", json={"query": query}, headers=H(keys["viewer"]))
    assert r.status_code == status and r.json()["error"]["code"] == code
    assert "internal.example" not in r.text  # upstream details stay in the server log
    if query == "AMBIG":
        assert r.json()["error"]["candidates"] == ["star A", "star B"]


@pytest.mark.parametrize("body", [{}, {"query": ""}, {"query": "x" * 121}, {"query": "a", "extra": 1}])
def test_search_input_is_validated(client, keys, body):
    assert client.post("/v1/objects/search", json=body, headers=H(keys["viewer"])).status_code == 422


def test_unknown_objects_and_bad_ids(client, keys):
    z = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/v1/objects/{z}", headers=H(keys["viewer"])).status_code == 404
    assert client.get(f"/v1/objects/{z}/observations", headers=H(keys["viewer"])).status_code == 404
    assert client.get("/v1/objects/not-a-uuid", headers=H(keys["viewer"])).status_code == 422


def test_observations_list_and_filter(client, services, keys):
    obj = client.post("/v1/objects/search", json={"query": "TIC 1"}, headers=H(keys["viewer"])).json()
    assert client.get(f"/v1/objects/{obj['object_id']}/observations", headers=H(keys["viewer"])).json() == []
    with services.context() as ctx:
        o = ctx.repo.get_object(__import__("uuid").UUID(obj["object_id"]))
    add_observation(services, o, make_lc(1))
    rows = client.get(f"/v1/objects/{obj['object_id']}/observations", headers=H(keys["viewer"])).json()
    assert len(rows) == 1 and rows[0]["segment"] == 7 and rows[0]["dataset"] == "TESS-SPOC"
    assert "artifact" not in str(rows[0]).lower() and "path" not in rows[0]  # no storage internals
    f = client.get(f"/v1/objects/{obj['object_id']}/observations?modality=spectrum", headers=H(keys["viewer"]))
    assert f.json() == []


def test_observation_data_is_downsampled_normalised_and_nan_safe(client, services, keys):
    obj = client.post("/v1/objects/search", json={"query": "TIC 1"}, headers=H(keys["viewer"])).json()
    with services.context() as ctx:
        o = ctx.repo.get_object(__import__("uuid").UUID(obj["object_id"]))
    lc = make_lc(1, __import__("conftest").planet(make_lc(1)))
    lc.flux[10] = np.nan
    lc.native_quality[11] = 32
    obs_id = add_observation(services, o, lc)
    full = client.get(f"/v1/observations/{obs_id}/data?max_points=20000", headers=H(keys["viewer"])).json()
    assert full["n_returned"] == full["n_total"] == len(lc.flux) and not full["downsampled"]
    assert full["flux"][10] is None and full["quality_flagged"][11] is True
    assert 0.98 < float(np.nanmedian([v for v in full["flux"] if v is not None])) < 1.02  # median-normalised
    small = client.get(f"/v1/observations/{obs_id}/data?max_points=100", headers=H(keys["viewer"])).json()
    assert small["downsampled"] and small["n_returned"] <= 102 and small["n_total"] == full["n_total"]
    dip = min(v for v in full["flux"] if v is not None)
    assert min(v for v in small["flux"] if v is not None) == pytest.approx(dip)  # the transit survives
    z = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/v1/observations/{z}/data", headers=H(keys["viewer"])).status_code == 404
    for bad in (10, 50000):
        assert client.get(f"/v1/observations/{obs_id}/data?max_points={bad}", headers=H(keys["viewer"])).status_code == 422
