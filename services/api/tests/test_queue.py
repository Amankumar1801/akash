import dataclasses
import json
import sqlite3
import subprocess
import sys
import threading
import time

import pytest
from akash_api.app import create_app
from akash_api.jobs import QUEUED, RUNNING, JobStore, QueueExecutor
from akash_api.queue_worker import run_worker
from akash_api.worker import execute_job
from akash_core.config import Settings
from akash_core.preflight import check
from conftest import H, submit, wait_done
from fastapi.testclient import TestClient


def work(sv, wid, **kw):
    """run_worker with a hard stop, so a bug can never hang the suite."""
    stop = threading.Event()
    timer = threading.Timer(60, stop.set)
    timer.start()
    try:
        return run_worker(sv, wid, stop=stop, **kw)
    finally:
        timer.cancel()


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def new_store(tmp_path, clock=None):
    conn = sqlite3.connect(tmp_path / "q.sqlite3")
    return JobStore(conn, clock or time.time), conn


def add(store, n, kind="investigation"):
    ids = []
    for i in range(n):
        j, _ = store.create(f"job-{i}-{kind}", kind, "rita", {"i": i}, f"k{i}{kind}")
        ids.append(j.job_id)
    return ids


# ---------- leases ----------
def test_claim_is_fifo_and_filters_by_kind(tmp_path):
    clock = Clock()
    s, _ = new_store(tmp_path, clock)
    a = add(s, 1)
    clock.t += 1
    other = add(s, 1, kind="other")
    clock.t += 1
    b, _ = s.create("late", "investigation", "rita", {}, "klate")
    job, attempt = s.claim_next("w1", 30)
    assert job.job_id == a[0] and attempt == 1 and job.status == RUNNING
    assert s.claim_next("w1", 30)[0].job_id == b.job_id
    assert s.claim_next("w1", 30) is None and s.get(other[0]).status == QUEUED


def test_two_processes_never_claim_the_same_job(tmp_path):
    s, _ = new_store(tmp_path)
    ids = add(s, 40)
    code = (
        "import sys,sqlite3\nfrom akash_api.jobs import JobStore\n"
        "c=sqlite3.connect(sys.argv[1],timeout=20)\nc.execute('PRAGMA busy_timeout=20000')\n"
        "s=JobStore(c)\nout=[]\n"
        "while True:\n r=s.claim_next(sys.argv[2],60)\n if r is None: break\n out.append(r[0].job_id)\n"
        "print(','.join(out))\n"
    )
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(tmp_path / "q.sqlite3"), f"w{i}"],
            stdout=subprocess.PIPE,
            text=True,
        )
        for i in range(3)
    ]
    got = [p.communicate(timeout=60)[0].strip().split(",") for p in procs]
    flat = [x for g in got for x in g if x]
    assert sorted(flat) == sorted(ids) and len(set(flat)) == len(flat) == 40


def test_heartbeat_extends_and_rejects_the_wrong_owner(tmp_path):
    clock = Clock()
    s, _ = new_store(tmp_path, clock)
    add(s, 1)
    job, _ = s.claim_next("w1", 10)
    clock.t += 8
    assert s.heartbeat(job.job_id, "w1", 10) and not s.heartbeat(job.job_id, "intruder", 10)
    clock.t += 8  # 16s since claim, but renewed at 8s
    assert s.reap_expired(3) == []


def test_expired_lease_requeues_then_fails_after_max_attempts(tmp_path):
    clock = Clock()
    s, _ = new_store(tmp_path, clock)
    (jid,) = add(s, 1)
    for attempt in (1, 2):
        job, n = s.claim_next("w", 10)
        assert n == attempt
        clock.t += 11
        assert s.reap_expired(3) == [(jid, "requeued")] and s.get(jid).status == QUEUED
    s.claim_next("w", 10)
    clock.t += 11
    assert s.reap_expired(3) == [(jid, "failed")]
    j = s.get(jid)
    assert j.status == "failed" and "stopped responding" in j.error
    kinds = [e["kind"] for e in s.events_after(jid)]
    assert kinds.count("job_requeued") == 2 and kinds[-1] == "job_failed"


def test_jobs_without_a_lease_are_never_reaped(tmp_path):
    clock = Clock()
    s, _ = new_store(tmp_path, clock)
    (jid,) = add(s, 1)
    assert s.mark_running(jid)  # the in-process path
    clock.t += 10_000
    assert s.reap_expired(3) == [] and s.get(jid).status == RUNNING


def test_an_old_database_is_migrated(tmp_path):
    c = sqlite3.connect(tmp_path / "old.sqlite3")
    c.execute(
        "CREATE TABLE job (job_id TEXT PRIMARY KEY, kind TEXT NOT NULL, owner TEXT NOT NULL, "
        "status TEXT NOT NULL, created_at REAL NOT NULL, started_at REAL, finished_at REAL, "
        "error TEXT, idempotency_key TEXT NOT NULL, params TEXT NOT NULL, "
        "cancel_requested INTEGER NOT NULL DEFAULT 0, outcome TEXT, category TEXT)"
    )
    c.execute(
        "INSERT INTO job VALUES ('old','investigation','rita','queued',1,NULL,NULL,NULL,'k','{}',0,NULL,NULL)"
    )
    c.commit()
    s = JobStore(c)
    assert s.claim_next("w", 10)[0].job_id == "old"


# ---------- end to end through the API ----------
@pytest.fixture
def qservices(services):
    return dataclasses.replace(services, executor=QueueExecutor())


@pytest.fixture
def qclient(qservices, keys):
    with TestClient(create_app(qservices.settings, qservices)) as c:
        yield c


def test_the_api_only_enqueues_and_a_worker_finishes_the_job(qclient, qservices, keys):
    inv = submit(qclient, keys["researcher"]).json()["investigation_id"]
    time.sleep(0.3)
    assert (
        qclient.get(f"/v1/investigations/{inv}", headers=H(keys["researcher"])).json()["status"]
        == "queued"
    )
    assert work(qservices, "w1", max_jobs=1) == 1
    body = wait_done(qclient, H(keys["researcher"]), inv, timeout=60)
    assert body["status"] == "succeeded" and body["assessment"] is not None
    ev = qclient.get(f"/v1/investigations/{inv}/events", headers=H(keys["researcher"]))
    assert ev.status_code == 200


def test_queued_jobs_survive_an_api_restart(qservices, keys):
    with TestClient(create_app(qservices.settings, qservices)) as c:
        inv = submit(c, keys["researcher"]).json()["investigation_id"]
    with TestClient(create_app(qservices.settings, qservices)) as c2:  # lifespan runs again
        assert (
            c2.get(f"/v1/investigations/{inv}", headers=H(keys["researcher"])).json()["status"]
            == "queued"
        )
        work(qservices, "w1", max_jobs=1)
        assert wait_done(c2, H(keys["researcher"]), inv, timeout=60)["status"] == "succeeded"


def test_a_job_cancelled_while_queued_is_never_run(qclient, qservices, keys):
    inv = submit(qclient, keys["researcher"]).json()["investigation_id"]
    assert (
        qclient.delete(f"/v1/investigations/{inv}", headers=H(keys["researcher"])).status_code
        == 202
    )
    stop = threading.Event()
    threading.Timer(0.4, stop.set).start()
    assert run_worker(qservices, "w1", stop=stop) == 0  # nothing left to claim
    assert (
        qclient.get(f"/v1/investigations/{inv}", headers=H(keys["researcher"])).json()["status"]
        == "cancelled"
    )


def test_cancelling_a_running_job_reaches_the_worker_through_the_database(qclient, qservices, keys):
    inv = submit(qclient, keys["researcher"]).json()["investigation_id"]

    def cancel_then_run(sv, jid):
        r = qclient.delete(f"/v1/investigations/{jid}", headers=H(keys["researcher"]))
        assert r.status_code == 202  # job is running, so only a flag is set
        execute_job(sv, jid, claimed=True)

    work(qservices, "w1", max_jobs=1, run=cancel_then_run)
    assert wait_done(qclient, H(keys["researcher"]), inv, timeout=30)["status"] == "cancelled"


def test_a_retry_after_a_crash_between_saving_and_finishing_succeeds(qclient, qservices, keys):
    inv = submit(qclient, keys["researcher"]).json()["investigation_id"]
    work(qservices, "w1", max_jobs=1)
    assert wait_done(qclient, H(keys["researcher"]), inv, timeout=60)["status"] == "succeeded"
    with qservices.context() as ctx:  # as if the worker died after save()
        ctx.conn.execute(
            "UPDATE job SET status='running', finished_at=NULL, lease_owner='dead', "
            "lease_until=1 WHERE job_id=?",
            (inv,),
        )
        ctx.conn.commit()
    work(qservices, "w2", max_jobs=1)  # reaps, requeues, runs attempt 2
    body = wait_done(qclient, H(keys["researcher"]), inv, timeout=60)
    assert body["status"] == "succeeded"
    with qservices.context() as ctx:
        assert JobStore(ctx.conn).attempts(inv) == 2


def test_a_running_worker_keeps_its_lease_with_heartbeats(qclient, qservices, keys):
    fast = dataclasses.replace(
        qservices,
        settings=qservices.settings.model_copy(
            update={"worker_lease_s": 0.6, "worker_poll_s": 0.05}
        ),
    )
    inv = submit(qclient, keys["researcher"]).json()["investigation_id"]
    seen = []

    def slow(sv, jid):
        time.sleep(1.8)  # three lease periods
        with sv.context() as ctx:
            seen.append(JobStore(ctx.conn).reap_expired(3))
        execute_job(sv, jid, claimed=True)

    work(fast, "w1", max_jobs=1, run=slow)
    assert seen == [[]]
    assert wait_done(qclient, H(keys["researcher"]), inv, timeout=60)["status"] == "succeeded"


def test_worker_stops_when_asked(qservices):
    stop = threading.Event()
    t = threading.Thread(target=lambda: run_worker(qservices, "w", stop=stop))
    t.start()
    time.sleep(0.2)
    stop.set()
    t.join(timeout=5)
    assert not t.is_alive()


def test_preflight_validates_the_executor_setting(tmp_path):
    base = Settings(env="dev", sqlite_path=str(tmp_path / "a.db"), data_dir=str(tmp_path))
    assert any(
        f.code == "executor_invalid"
        for f in check(base.model_copy(update={"api_executor": "celery"}))
    )
    codes = [f.code for f in check(base.model_copy(update={"api_executor": "queue"}))]
    assert "queue_needs_worker" in codes
    assert any(
        f.code == "worker_limits"
        for f in check(base.model_copy(update={"api_executor": "queue", "worker_lease_s": 1.0}))
    )
    assert json.dumps(codes)
