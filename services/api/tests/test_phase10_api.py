import time

import numpy as np
from akash_api.auth import ApiKeyStore
from akash_science.synthetic import make_synthetic_lc
from conftest import H, submit, wait_done

CFG = {"n_trials": 4, "n_controls": 0, "seed": 1, "period_min_d": 1.0, "period_max_d": 3.0,
       "depth_min_ppm": 4000, "depth_max_ppm": 8000}


def small(services):
    services.experiment_base = lambda g: make_synthetic_lc(g, days=8, cadence_s=1800, gap=None)


def post(client, keys, body, who="researcher"):
    return client.post("/v1/experiments", json=body, headers=H(keys[who]))


def wait_exp(client, keys, eid, who="researcher", timeout=120):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        e = client.get(f"/v1/experiments/{eid}", headers=H(keys[who])).json()
        if e["status"] in ("succeeded", "failed", "cancelled"):
            return e
        time.sleep(0.05)
    raise AssertionError("experiment never finished")


def finished(client, keys, who="researcher"):
    inv = submit(client, keys[who], "TIC 1").json()["investigation_id"]
    wait_done(client, H(keys[who]), inv)
    return inv


# ---------- experiments ----------
def test_experiment_runs_and_reports_intervals_and_caveats(client, services, keys):
    small(services)
    r = post(client, keys, CFG)
    assert r.status_code == 202 and r.json()["total"] == 4
    e = wait_exp(client, keys, r.json()["experiment_id"])
    assert e["status"] == "succeeded" and e["done"] == 4 and e["error"] is None
    res = e["result"]
    assert res["n_trials"] == 4 and "synthetic" in res["noise_note"] and res["caveats"]
    assert res["config_sha256"] and res["false_alarm"] is None
    for b in res["by_snr"]:
        rec = b["recovered"]
        assert (rec["rate"] is None) == (rec["n"] == 0)  # no data, no number


def test_experiment_is_deterministic_for_a_seed(client, services, keys):
    small(services)
    a = wait_exp(client, keys, post(client, keys, CFG).json()["experiment_id"])
    b = wait_exp(client, keys, post(client, keys, CFG).json()["experiment_id"])
    assert a["result"] == b["result"]


def test_experiment_input_is_validated(client, keys):
    for bad in ({**CFG, "n_trials": 10_000}, {**CFG, "period_min_d": 9, "period_max_d": 2},
                {**CFG, "noise_source": "real"}, {**CFG, "extra": 1}, {**CFG, "seed": -1}):
        assert post(client, keys, bad).status_code in (400, 422)


def test_experiments_are_private_and_need_researcher(client, services, keys):
    small(services)
    eid = post(client, keys, CFG).json()["experiment_id"]
    assert post(client, keys, CFG, who="viewer").status_code == 403
    assert client.get(f"/v1/experiments/{eid}", headers=H(keys["researcher2"])).status_code == 404
    assert client.delete(f"/v1/experiments/{eid}", headers=H(keys["researcher2"])).status_code == 404
    assert client.get(f"/v1/experiments/{eid}", headers=H(keys["admin"])).status_code == 200
    assert client.get("/v1/experiments", headers=H(keys["researcher2"])).json() == []
    wait_exp(client, keys, eid)


def test_one_active_experiment_per_user_and_cancel(client, services, keys):
    services.experiment_base = lambda g: (time.sleep(0.3), make_synthetic_lc(
        g, days=6, cadence_s=1800, gap=None))[1]
    first = post(client, keys, {**CFG, "n_trials": 12}).json()["experiment_id"]
    assert post(client, keys, CFG).status_code == 409
    assert client.delete(f"/v1/experiments/{first}", headers=H(keys["researcher"])).status_code == 202
    e = wait_exp(client, keys, first)
    assert e["status"] == "cancelled" and e["done"] < 12
    assert client.delete(f"/v1/experiments/{first}", headers=H(keys["researcher"])).status_code == 409


def test_experiment_failure_is_sanitised(client, services, keys, caplog):
    def boom(g):
        raise RuntimeError("secret internal path /srv/x")
    services.experiment_base = boom
    e = wait_exp(client, keys, post(client, keys, CFG).json()["experiment_id"])
    assert e["status"] == "failed" and "secret" not in str(e) and "/srv" not in str(e)


def test_experiments_stranded_by_a_crash_are_failed_on_startup(services, keys):
    from akash_api.research import ExperimentStore
    with services.context() as ctx:
        s = ExperimentStore(ctx.conn)
        s.create("e-1", "rita", {}, "x", 1)
        assert s.recover_orphans() == 1 and s.get("e-1").status == "failed"


# ---------- labels ----------
def label(client, keys, inv, lab="interesting", note=None, who="researcher"):
    body = {"label": lab, **({"note": note} if note is not None else {})}
    return client.post(f"/v1/investigations/{inv}/labels", json=body, headers=H(keys[who]))


def test_labels_store_the_category_shown_at_review_time(client, keys):
    inv = finished(client, keys)
    r = label(client, keys, inv, "needs_followup", "odd depth\x00 variation")
    assert r.status_code == 201 and r.json()["reviewer"] == "rita"
    cat = client.get(f"/v1/investigations/{inv}", headers=H(keys["researcher"])).json()["category"]
    assert r.json()["triage_category"] == cat and "\x00" not in r.json()["note"]
    label(client, keys, inv, "false_positive")
    got = client.get(f"/v1/investigations/{inv}/labels", headers=H(keys["viewer"] if False
                                                                    else keys["researcher"])).json()
    assert [x["label"] for x in got] == ["needs_followup", "false_positive"]  # history kept


def test_label_validation_privacy_and_state(client, keys):
    from conftest import GATE
    inv = finished(client, keys)
    assert label(client, keys, inv, "maybe").status_code in (400, 422)
    assert label(client, keys, inv, note="x" * 501).status_code in (400, 422)
    assert label(client, keys, inv, who="viewer").status_code == 403
    assert label(client, keys, inv, who="researcher2").status_code == 404
    GATE.clear()
    j = submit(client, keys["researcher"], "TIC 9").json()["investigation_id"]
    assert label(client, keys, j).status_code == 409
    GATE.set()
    wait_done(client, H(keys["researcher"]), j)


def test_export_is_admin_only_and_latest_per_reviewer(client, keys):
    inv = finished(client, keys)
    label(client, keys, inv, "interesting")
    label(client, keys, inv, "uncertain")
    assert client.get("/v1/labels/export", headers=H(keys["researcher"])).status_code == 403
    ex = client.get("/v1/labels/export", headers=H(keys["admin"])).json()
    mine = [r for r in ex["rows"] if r["investigation_id"] == inv]
    assert len(mine) == 1 and mine[0]["label"] == "uncertain" and "needs_followup" in ex["labels"]


# ---------- observability ----------
def test_metrics_count_requests_by_route_template_not_by_id(client, keys):
    inv = finished(client, keys)
    for _ in range(3):
        client.get(f"/v1/investigations/{inv}", headers=H(keys["researcher"]))
    client.get("/v1/nope", headers=H(keys["researcher"]))
    m = client.get("/v1/metrics", headers=H(keys["admin"])).json()
    routes = {s["labels"]["route"] for s in m["counters"]["http_requests_total"]}
    assert "/v1/investigations/{investigation_id}" in routes and inv not in " ".join(routes)
    assert "unmatched" in routes
    jobs = m["counters"]["jobs_total"]
    assert any(s["labels"]["status"] == "succeeded" for s in jobs)
    assert m["histograms"]["http_request_seconds"][0]["count"] >= 1


def test_metrics_are_admin_only_and_prometheus_text_is_well_formed(client, keys):
    assert client.get("/v1/metrics", headers=H(keys["researcher"])).status_code == 403
    assert client.get("/v1/metrics").status_code == 401
    client.get("/v1/health")
    txt = client.get("/v1/metrics?format=prometheus", headers=H(keys["admin"])).text
    assert "# TYPE akash_http_requests_total counter" in txt
    assert 'akash_http_request_seconds_bucket{route="/v1/health",le="+Inf"}' in txt
    assert client.get("/v1/metrics?format=xml", headers=H(keys["admin"])).status_code in (400, 422)


def test_metrics_series_cap_prevents_cardinality_blowup():
    from akash_api.metrics import MAX_SERIES, Metrics
    m = Metrics()
    for i in range(MAX_SERIES + 50):
        m.inc("x", {"id": str(i)})
    series = m.snapshot()["counters"]["x"]
    assert len(series) == MAX_SERIES + 1 and any("_overflow" in s["labels"] for s in series)


def test_prometheus_label_escaping():
    from akash_api.metrics import Metrics
    m = Metrics()
    m.inc("x", {"a": 'q"\\\n'})
    assert 'a="q\\"\\\\\\n"' in m.prometheus()


def test_agent_and_report_activity_is_counted(client, keys):
    inv = finished(client, keys)
    client.post(f"/v1/investigations/{inv}/ask", json={"question": "why?"}, headers=H(keys["researcher"]))
    client.post("/v1/reports", json={"investigation_id": inv}, headers=H(keys["researcher"]))
    c = client.get("/v1/metrics", headers=H(keys["admin"])).json()["counters"]
    assert c["agent_runs_total"][0]["labels"]["mode"] == "deterministic"
    assert c["reports_total"][0]["labels"]["format"] == "json"


def test_trace_joins_requests_and_job_events_in_time_order(client, services, keys):
    inv = finished(client, keys)
    client.post(f"/v1/investigations/{inv}/ask", json={"question": "why?"}, headers=H(keys["researcher"]))
    t = client.get(f"/v1/investigations/{inv}/trace", headers=H(keys["researcher"])).json()
    kinds = [(x["source"], x["kind"]) for x in t["timeline"]]
    assert ("request", "investigation.create") in kinds and ("job", "job_succeeded") in kinds
    assert ("request", "agent.ask") in kinds
    ts = [x["ts"] for x in t["timeline"]]
    assert ts == sorted(ts) and t["trace_id"] == inv
    req = next(x for x in t["timeline"] if x["kind"] == "investigation.create")
    assert req["request_id"]
    with services.context() as ctx:
        assert any(e["request_id"] == req["request_id"]
                   for e in ApiKeyStore(ctx.conn).audit_entries("investigation.create"))
    assert client.get(f"/v1/investigations/{inv}/trace", headers=H(keys["researcher2"])).status_code == 404
    assert np.isfinite(ts).all()
