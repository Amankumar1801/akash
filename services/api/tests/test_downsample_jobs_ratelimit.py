import threading

import numpy as np
import pytest
from akash_api.db import open_connection
from akash_api.downsample import minmax_indices
from akash_api.jobs import (
    CANCELLED,
    FAILED,
    QUEUED,
    RUNNING,
    SUCCEEDED,
    InProcessExecutor,
    JobStore,
)
from akash_api.ratelimit import RateLimiter


# ---------- downsampling ----------
def test_small_arrays_are_returned_whole():
    assert list(minmax_indices(np.arange(10.0), 50)) == list(range(10))


def test_envelope_keeps_extremes_endpoints_and_the_cap():
    rng = np.random.default_rng(0)
    y = rng.normal(0, 1, 50000)
    y[12345], y[40001] = -25.0, 30.0  # a transit-like dip and a flare-like spike
    idx = minmax_indices(y, 500)
    assert 12345 in idx and 40001 in idx and 0 in idx and len(y) - 1 in idx
    assert len(idx) <= 500 + 2 and (np.diff(idx) > 0).all()


def test_nan_handling_never_crashes():
    y = np.full(5000, np.nan)
    y[100:140] = np.linspace(0, 1, 40)
    idx = minmax_indices(y, 100)
    assert len(idx) <= 102 and 0 in idx


# ---------- job store ----------
@pytest.fixture
def jobs(tmp_path):
    return JobStore(open_connection(str(tmp_path / "j.sqlite3")))


def test_idempotency_is_per_owner_and_ignores_failed_jobs(jobs):
    a, created = jobs.create("j1", "inv", "alice", {"x": 1}, "k")
    b, created_b = jobs.create("j2", "inv", "alice", {"x": 1}, "k")
    assert created and not created_b and b.job_id == "j1"
    other, created_o = jobs.create("j3", "inv", "bob", {"x": 1}, "k")
    assert created_o and other.job_id == "j3"  # different owner: independent
    jobs.finish("j1", FAILED, error="x")
    again, created_a = jobs.create("j4", "inv", "alice", {"x": 1}, "k")
    assert created_a and again.job_id == "j4"  # a failed job may be resubmitted


def test_a_succeeded_job_is_returned_not_rerun(jobs):
    jobs.create("j1", "inv", "alice", {}, "k")
    jobs.mark_running("j1")
    jobs.finish("j1", SUCCEEDED, outcome="assessed", category="new_signal_review")
    job, created = jobs.create("j2", "inv", "alice", {}, "k")
    assert not created and job.status == SUCCEEDED and job.category == "new_signal_review"


def test_state_transitions_are_one_way(jobs):
    jobs.create("j1", "inv", "a", {}, "k")
    assert jobs.mark_running("j1") and not jobs.mark_running("j1")
    jobs.finish("j1", CANCELLED)
    jobs.finish("j1", SUCCEEDED)  # too late: terminal states never change
    assert jobs.get("j1").status == CANCELLED


def test_events_are_ordered_and_resumable(jobs):
    jobs.create("j1", "inv", "a", {}, "k")
    for i in range(5):
        jobs.append_event("j1", "phase", {"i": i})
    ev = jobs.events_after("j1", 0)
    assert [e["seq"] for e in ev] == [1, 2, 3, 4, 5, 6] and ev[0]["kind"] == "job_queued"
    assert [e["data"]["i"] for e in jobs.events_after("j1", 3)] == [2, 3, 4]


def test_concurrent_event_writers_get_unique_contiguous_sequences(tmp_path):
    path = str(tmp_path / "c.sqlite3")
    JobStore(open_connection(path)).create("j1", "inv", "a", {}, "k")

    def writer(tag: int) -> None:
        store = JobStore(open_connection(path))
        for i in range(25):
            store.append_event("j1", "phase", {"w": tag, "i": i})

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    seqs = [e["seq"] for e in JobStore(open_connection(path)).events_after("j1", 0, 1000)]
    assert seqs == list(range(1, 102))  # 1 queued + 100 writes, no gaps, no duplicates


def test_list_is_owner_scoped_and_paged(jobs):
    for i in range(5):
        jobs.create(f"a{i}", "inv", "alice", {}, f"k{i}")
    jobs.create("b0", "inv", "bob", {}, "kb")
    assert {j.owner for j in jobs.list_for_owner("alice", 100, 0)} == {"alice"}
    assert len(jobs.list_for_owner("alice", 2, 0)) == 2 and len(jobs.list_for_owner("alice", 2, 4)) == 1
    assert len(jobs.list_for_owner(None, 100, 0)) == 6  # admin view


def test_orphan_recovery_fails_stranded_jobs_visibly(jobs):
    jobs.create("q", "inv", "a", {}, "k1")
    jobs.create("r", "inv", "a", {}, "k2")
    jobs.mark_running("r")
    jobs.create("done", "inv", "a", {}, "k3")
    jobs.finish("done", SUCCEEDED)
    assert jobs.recover_orphans() == 2
    for jid in ("q", "r"):
        assert jobs.get(jid).status == FAILED and "restart" in jobs.get(jid).error
        assert jobs.events_after(jid, 0)[-1]["kind"] == "job_failed"
    assert jobs.get("done").status == SUCCEEDED


def test_cancel_flag_only_applies_to_live_jobs(jobs):
    jobs.create("j", "inv", "a", {}, "k")
    assert jobs.request_cancel("j").cancel_requested and jobs.cancel_requested("j")
    jobs.finish("j", CANCELLED)
    jobs.create("k", "inv", "a", {}, "k2")
    jobs.finish("k", SUCCEEDED)
    assert not jobs.request_cancel("k").cancel_requested  # finished: flag not set


def test_executor_runs_work_concurrently_and_shuts_down():
    ex, done, barrier = InProcessExecutor(2), [], threading.Barrier(2, timeout=5)
    ex.submit(lambda: (barrier.wait(), done.append(1)))
    ex.submit(lambda: (barrier.wait(), done.append(2)))
    ex.shutdown(wait=True)
    assert sorted(done) == [1, 2]  # both ran at once (the barrier would have timed out otherwise)


# ---------- rate limiter ----------
def test_token_bucket_allows_burst_then_refuses_then_refills():
    now = {"t": 0.0}
    rl = RateLimiter(clock=lambda: now["t"])
    assert all(rl.check("u", "b", 6) is None for _ in range(6))  # burst = limit
    wait = rl.check("u", "b", 6)
    assert wait is not None and wait == pytest.approx(10.0)  # 6/min => one token per 10 s
    now["t"] = 10.0
    assert rl.check("u", "b", 6) is None and rl.check("u", "b", 6) is not None


def test_buckets_and_principals_are_independent():
    rl = RateLimiter(clock=lambda: 0.0)
    for _ in range(3):
        assert rl.check("alice", "general", 3) is None
    assert rl.check("alice", "general", 3) is not None
    assert rl.check("bob", "general", 3) is None  # another principal
    assert rl.check("alice", "investigation", 3) is None  # another bucket
