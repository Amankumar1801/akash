import time
import uuid

import pytest
from akash_api.app import create_app
from akash_api.auth import ApiKeyStore
from akash_api.jobs import JobStore
from akash_fusion.progress import PHASES
from conftest import GATE, H, submit, wait_done
from fastapi.testclient import TestClient

TERMINAL = {"job_succeeded", "job_failed", "job_cancelled"}


def run(client, keys, query="TIC 1", who="researcher", **kw):
    r = submit(client, keys[who], query, **kw)
    assert r.status_code in (200, 202), r.text
    return r.json()["investigation_id"], r


def wait_status(client, keys, inv, want, who="researcher", timeout=30):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        s = client.get(f"/v1/investigations/{inv}", headers=H(keys[who])).json()["status"]
        if s == want:
            return
        time.sleep(0.02)
    raise AssertionError(f"never reached {want}, last {s}")


# ---------- the happy path ----------
def test_full_lifecycle_produces_a_stored_assessment(client, keys):
    inv, r = run(client, keys)
    body = r.json()
    assert r.status_code == 202 and body["status"] in ("queued", "running", "succeeded")
    assert body["links"]["events"] == f"/v1/investigations/{inv}/events" and not body["deduplicated"]
    done = wait_done(client, H(keys["researcher"]), inv)
    assert done["status"] == "succeeded" and done["outcome"] == "assessed" and done["error"] is None
    a = done["assessment"]
    assert a["triage_category"] == done["category"] and a["transit"]["snr"] > 15
    assert a["transit"]["period_d"]["value"] == pytest.approx(3.2, rel=0.01)
    assert done["n_evidence"] > 8 and done["started_at"] >= done["created_at"]
    assert done["finished_at"] >= done["started_at"]


def test_event_log_tells_the_whole_story_in_order(client, keys):
    inv, _ = run(client, keys)
    wait_done(client, H(keys["researcher"]), inv)
    ev = client.get(f"/v1/investigations/{inv}/log", headers=H(keys["researcher"])).json()
    assert [e["seq"] for e in ev] == list(range(1, len(ev) + 1))
    kinds = [e["kind"] for e in ev]
    assert kinds[:2] == ["job_queued", "job_started"] and kinds[-1] == "job_succeeded"
    phases = [e["data"]["phase"] for e in ev if e["kind"] == "phase"]
    for p in ("fetch_data", *PHASES):
        assert p in phases, p
    assert ev[1]["data"]["trace_id"] == inv  # the investigation id doubles as the trace id
    assert all(e["ts"] > 0 for e in ev) and ev[-1]["data"]["outcome"] == "assessed"
    tail = client.get(f"/v1/investigations/{inv}/log?after=5", headers=H(keys["researcher"])).json()
    assert [e["seq"] for e in tail] == [e["seq"] for e in ev if e["seq"] > 5]


def parse_sse(text: str):
    out = []
    for block in text.strip().split("\n\n"):
        f = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if f:
            out.append(f)
    return out


def test_sse_streams_replays_and_resumes(client, keys):
    inv, _ = run(client, keys)
    # open the stream immediately: it must follow the job live and end by itself
    with client.stream("GET", f"/v1/investigations/{inv}/events", headers=H(keys["researcher"])) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["cache-control"] == "no-cache"
        events = parse_sse("".join(r.iter_text()))
    kinds = [e["event"] for e in events]
    assert kinds[0] == "job_queued" and kinds[-1] == "job_succeeded" and "phase" in kinds
    ids = [int(e["id"]) for e in events]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    # resume with Last-Event-ID: only later events, nothing duplicated
    cut = ids[len(ids) // 2]
    h = {**H(keys["researcher"]), "Last-Event-ID": str(cut)}
    with client.stream("GET", f"/v1/investigations/{inv}/events", headers=h) as r2:
        resumed = parse_sse("".join(r2.iter_text()))
    assert [int(e["id"]) for e in resumed] == [i for i in ids if i > cut]
    with client.stream("GET", f"/v1/investigations/{inv}/events?after={ids[-2]}",
                       headers=H(keys["researcher"])) as r3:
        assert [e["event"] for e in parse_sse("".join(r3.iter_text()))] == ["job_succeeded"]


def test_sse_gives_up_cleanly_on_a_stalled_job(services, settings, keys):
    short = settings.model_copy(update={"api_sse_max_seconds": 0.3})
    services.settings = short
    with TestClient(create_app(short, services)) as c:
        inv, _ = run(c, keys, "TIC 5")
        wait_status(c, keys, inv, "running")
        with c.stream("GET", f"/v1/investigations/{inv}/events", headers=H(keys["researcher"])) as r:
            kinds = [e["event"] for e in parse_sse("".join(r.iter_text()))]
        assert kinds[-1] == "timeout"  # the client reconnects with Last-Event-ID; no hung socket
        GATE.set()
        wait_done(c, H(keys["researcher"]), inv)


def test_evidence_and_provenance_endpoints(client, keys):
    inv, _ = run(client, keys)
    done = wait_done(client, H(keys["researcher"]), inv)
    rows = client.get(f"/v1/investigations/{inv}/evidence", headers=H(keys["researcher"])).json()
    assert len(rows) == done["n_evidence"]
    sig = next(r for r in rows if r["observation"].startswith("Periodic dip search"))
    assert sig["source"]["uri"] == "https://mast.stsci.edu/fake"  # traced back to the fetch
    assert {r["channel"] for r in rows} >= {"observed_fact", "model_prediction", "catalog_status"}
    g = client.get(f"/v1/investigations/{inv}/provenance", headers=H(keys["researcher"])).json()
    assert g["roots_verifiable"] is True and g["nodes"] and g["edges"]
    roots = [n for n in g["nodes"] if n["source_uri"]]
    assert roots and all(n["sha256"] for n in roots)
    ids = {n["prov_id"] for n in g["nodes"]}
    assert all(e["from_prov"] in ids and e["to_prov"] in ids for e in g["edges"])


def test_no_signal_is_a_successful_outcome_without_an_assessment(client, keys):
    inv, _ = run(client, keys, "TIC 2")
    done = wait_done(client, H(keys["researcher"]), inv)
    assert done["status"] == "succeeded" and done["outcome"] == "no_transit_signal"
    assert done["assessment"] is None and done["category"] is None


def test_quick_mode_skips_archive_lookups(client, keys):
    inv, _ = run(client, keys, mode="quick")
    done = wait_done(client, H(keys["researcher"]), inv)
    assert done["status"] == "succeeded"
    assert done["assessment"]["known_status"] is None  # no catalog consulted in quick mode


# ---------- ownership & authorization ----------
def test_investigations_are_private_to_their_owner(client, keys):
    inv, _ = run(client, keys)
    wait_done(client, H(keys["researcher"]), inv)
    base = f"/v1/investigations/{inv}"
    for who in ("researcher2", "viewer"):  # another researcher and a viewer
        for suffix in ("", "/log", "/evidence", "/provenance", "/events"):
            r = client.get(base + suffix, headers=H(keys[who]))
            assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", (who, suffix)
    assert client.delete(base, headers=H(keys["researcher2"])).status_code == 404
    assert client.get(base, headers=H(keys["admin"])).status_code == 200
    mine = client.get("/v1/investigations", headers=H(keys["researcher"])).json()
    assert [j["investigation_id"] for j in mine] == [inv]
    assert client.get("/v1/investigations", headers=H(keys["researcher2"])).json() == []
    assert inv in [j["investigation_id"] for j in client.get("/v1/investigations", headers=H(keys["admin"])).json()]


def test_a_missing_investigation_looks_the_same_as_someone_elses(client, keys):
    other, _ = run(client, keys)
    r1 = client.get(f"/v1/investigations/{other}", headers=H(keys["researcher2"]))
    r2 = client.get(f"/v1/investigations/{uuid.uuid4()}", headers=H(keys["researcher2"]))
    assert r1.status_code == r2.status_code == 404
    assert r1.json()["error"]["code"] == r2.json()["error"]["code"]  # no enumeration oracle
    wait_done(client, H(keys["researcher"]), other)


# ---------- idempotency ----------
def test_identical_requests_are_deduplicated_per_owner(client, keys):
    a, ra = run(client, keys, segments=[2, 1, 2])
    b, rb = run(client, keys, segments=[1, 2])  # same set, different order/duplicates
    assert a == b and ra.status_code == 202 and rb.status_code == 200 and rb.json()["deduplicated"]
    wait_done(client, H(keys["researcher"]), a)
    c, rc = run(client, keys, segments=[1, 2])  # even after success: returned, not re-run
    assert c == a and rc.status_code == 200
    d, _ = run(client, keys, segments=[3])  # different params => new investigation
    e, re_ = run(client, keys, segments=[1, 2], who="researcher2")  # another owner => new
    assert len({a, d, e}) == 3 and re_.status_code == 202
    for who, inv in (("researcher", d), ("researcher2", e)):
        wait_done(client, H(keys[who]), inv)


def test_a_failed_investigation_can_be_resubmitted(client, keys):
    a, _ = run(client, keys, "TIC 3")
    assert wait_done(client, H(keys["researcher"]), a)["status"] == "failed"
    b, rb = run(client, keys, "TIC 3")
    assert b != a and rb.status_code == 202 and not rb.json()["deduplicated"]
    wait_done(client, H(keys["researcher"]), b)


# ---------- failures are visible, sanitized, and terminal ----------
def test_upstream_failures_do_not_leak_internals(client, keys):
    inv, _ = run(client, keys, "TIC 3")
    done = wait_done(client, H(keys["researcher"]), inv)
    assert done["status"] == "failed" and done["error"] == "ProviderError: an upstream archive request failed"
    ev = client.get(f"/v1/investigations/{inv}/log", headers=H(keys["researcher"])).json()
    assert ev[-1]["kind"] == "job_failed" and "internal.example" not in str(ev)


def test_unexpected_crashes_are_logged_not_shown(client, keys, caplog):
    inv, _ = run(client, keys, "TIC 4")
    done = wait_done(client, H(keys["researcher"]), inv)
    assert done["status"] == "failed" and done["error"] == "internal error (see server logs)"
    blob = str(client.get(f"/v1/investigations/{inv}/log", headers=H(keys["researcher"])).json())
    assert "passwd" not in blob and "hunter2" not in blob and "boom" not in blob
    assert any("crashed" in r.getMessage() for r in caplog.records)  # the detail went to the log


# ---------- request validation ----------
@pytest.mark.parametrize("body", [
    {}, {"object_id": str(uuid.uuid4()), "query": "TIC 1"}, {"query": "TIC 1", "extra": 1},
    {"query": "TIC 1", "mission": "hubble"}, {"query": "TIC 1", "mode": "turbo"},
    {"query": "TIC 1", "segments": list(range(41))}, {"query": "TIC 1", "segments": [-1]},
    {"query": "TIC 1", "max_observations": 0}, {"query": "TIC 1", "max_observations": 41},
    {"query": ""}, {"query": "x" * 121}, {"object_id": "not-a-uuid"}])
def test_bad_requests_never_create_jobs(client, keys, body):
    assert client.post("/v1/investigations", json=body, headers=H(keys["researcher"])).status_code == 422
    assert client.get("/v1/investigations", headers=H(keys["researcher"])).json() == []


@pytest.mark.parametrize("body,status,code", [
    ({"query": "nonsense"}, 404, "object_not_found"), ({"query": "AMBIG"}, 409, "ambiguous_identity"),
    ({"query": "DOWN"}, 502, "upstream_error"), ({"object_id": str(uuid.uuid4())}, 404, "object_not_found")])
def test_unresolvable_targets_fail_fast_without_creating_jobs(client, keys, body, status, code):
    r = client.post("/v1/investigations", json=body, headers=H(keys["researcher"]))
    assert r.status_code == status and r.json()["error"]["code"] == code
    assert client.get("/v1/investigations", headers=H(keys["researcher"])).json() == []


def test_object_id_targets_work_like_queries(client, keys):
    obj = client.post("/v1/objects/search", json={"query": "TIC 2"}, headers=H(keys["viewer"])).json()
    r = client.post("/v1/investigations", json={"object_id": obj["object_id"]}, headers=H(keys["researcher"]))
    assert r.status_code == 202
    assert wait_done(client, H(keys["researcher"]), r.json()["investigation_id"])["object_id"] == obj["object_id"]


# ---------- cancellation ----------
def test_cancelling_a_running_job_stops_it_between_phases(client, keys):
    inv, _ = run(client, keys, "TIC 5")
    wait_status(client, keys, inv, "running")
    r = client.delete(f"/v1/investigations/{inv}", headers=H(keys["researcher"]))
    assert r.status_code == 202 and r.json()["cancel_requested"] is True and r.json()["status"] == "running"
    GATE.set()  # the blocked fetch returns; the next progress event notices the cancellation
    done = wait_done(client, H(keys["researcher"]), inv)
    assert done["status"] == "cancelled" and done["assessment"] is None
    ev = client.get(f"/v1/investigations/{inv}/log", headers=H(keys["researcher"])).json()
    assert ev[-1]["kind"] == "job_cancelled"
    assert client.delete(f"/v1/investigations/{inv}", headers=H(keys["researcher"])).status_code == 409
    assert client.get(f"/v1/investigations/{inv}/evidence", headers=H(keys["researcher"])).json() == []


def test_cancelling_a_queued_job_is_immediate_and_it_never_runs(client, keys):
    blockers = [run(client, keys, "TIC 5", segments=[i])[0] for i in (1, 2)]  # occupy both workers
    for b in blockers:
        wait_status(client, keys, b, "running")
    queued, _ = run(client, keys, "TIC 1")
    assert client.get(f"/v1/investigations/{queued}", headers=H(keys["researcher"])).json()["status"] == "queued"
    r = client.delete(f"/v1/investigations/{queued}", headers=H(keys["researcher"]))
    assert r.status_code == 202 and r.json()["status"] == "cancelled"
    GATE.set()
    for b in blockers:
        wait_done(client, H(keys["researcher"]), b)
    time.sleep(0.3)  # give a (wrongly) revived worker the chance to run it
    ev = client.get(f"/v1/investigations/{queued}/log", headers=H(keys["researcher"])).json()
    assert [e["kind"] for e in ev] == ["job_queued", "job_cancelled"]  # it never started


# ---------- concurrency & recovery ----------
def test_concurrent_jobs_do_not_interfere(client, keys):
    ids = [run(client, keys, q)[0] for q in ("TIC 1", "TIC 2", "TIC 6")]
    results = [wait_done(client, H(keys["researcher"]), i) for i in ids]
    assert [r["status"] for r in results] == ["succeeded"] * 3
    assert [r["outcome"] for r in results] == ["assessed", "no_transit_signal", "assessed"]
    for i in ids:
        ev = client.get(f"/v1/investigations/{i}/log", headers=H(keys["researcher"])).json()
        assert [e["seq"] for e in ev] == list(range(1, len(ev) + 1)) and ev[-1]["kind"] in TERMINAL
    assert len({r["investigation_id"] for r in results}) == 3


def test_listing_is_paged(client, keys):
    ids = [run(client, keys, "TIC 2", segments=[i])[0] for i in (1, 2, 3)]
    for i in ids:
        wait_done(client, H(keys["researcher"]), i)
    p1 = client.get("/v1/investigations?limit=2", headers=H(keys["researcher"])).json()
    p2 = client.get("/v1/investigations?limit=2&offset=2", headers=H(keys["researcher"])).json()
    assert len(p1) == 2 and len(p2) == 1 and {j["investigation_id"] for j in p1 + p2} == set(ids)
    assert client.get("/v1/investigations?limit=101", headers=H(keys["researcher"])).status_code == 422


def test_jobs_stranded_by_a_crash_are_failed_on_startup(services, settings, keys):
    services.ensure_schema()
    with services.context() as ctx:
        jobs = JobStore(ctx.conn)
        jobs.create("00000000-0000-0000-0000-00000000dead", "investigation", "rita", {"object_id": str(uuid.uuid4())}, "k")
        jobs.mark_running("00000000-0000-0000-0000-00000000dead")
    with TestClient(create_app(settings, services)) as c:  # startup runs recovery
        body = c.get("/v1/investigations/00000000-0000-0000-0000-00000000dead", headers=H(keys["admin"])).json()
        assert body["status"] == "failed" and "restart" in body["error"]


def test_create_and_cancel_are_audited_by_owner_name(client, services, keys):
    inv, _ = run(client, keys, "TIC 5")
    wait_status(client, keys, inv, "running")
    client.delete(f"/v1/investigations/{inv}", headers=H(keys["researcher"]))
    GATE.set()
    wait_done(client, H(keys["researcher"]), inv)
    with services.context() as ctx:
        e = ApiKeyStore(ctx.conn).audit_entries()
    acts = [(x["principal"], x["action"], x["resource"], x["outcome"]) for x in e if x["action"].startswith("investigation")]
    assert ("rita", "investigation.create", inv, "accepted") in acts
    assert ("rita", "investigation.cancel", inv, "requested") in acts
