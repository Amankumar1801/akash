"""Durable job records + ordered progress events + an executor interface.

Event `seq` is assigned inside a single INSERT..SELECT (atomic), with retry on the rare
primary-key race between two writers. Idempotency is per owner: a partial unique index covers
only jobs that are queued/running/succeeded, so a failed or cancelled job can be resubmitted."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol

QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED = ("queued", "running", "succeeded", "failed",
                                                  "cancelled")
TERMINAL = frozenset({SUCCEEDED, FAILED, CANCELLED})
TERMINAL_EVENT_KINDS = frozenset({"job_succeeded", "job_failed", "job_cancelled"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS job (
  job_id TEXT PRIMARY KEY, kind TEXT NOT NULL, owner TEXT NOT NULL, status TEXT NOT NULL,
  created_at REAL NOT NULL, started_at REAL, finished_at REAL, error TEXT,
  idempotency_key TEXT NOT NULL, params TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0,
  outcome TEXT, category TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS uq_job_idem ON job(owner, idempotency_key)
  WHERE status IN ('queued','running','succeeded');
CREATE INDEX IF NOT EXISTS idx_job_owner ON job(owner, created_at);
CREATE TABLE IF NOT EXISTS job_event (
  job_id TEXT NOT NULL, seq INTEGER NOT NULL, ts REAL NOT NULL, kind TEXT NOT NULL,
  payload TEXT NOT NULL, PRIMARY KEY (job_id, seq));
"""


@dataclass(frozen=True)
class Job:
    job_id: str
    kind: str
    owner: str
    status: str
    created_at: float
    started_at: float | None
    finished_at: float | None
    error: str | None
    params: dict[str, Any]
    cancel_requested: bool
    outcome: str | None
    category: str | None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL


def _row_to_job(r: sqlite3.Row | tuple[Any, ...]) -> Job:
    return Job(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], json.loads(r[8]), bool(r[9]),
               r[10], r[11])


_COLS = ("job_id, kind, owner, status, created_at, started_at, finished_at, error, params, "
         "cancel_requested, outcome, category")


class JobStore:
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time) -> None:
        self._c, self._clock = conn, clock
        self._c.executescript(_SCHEMA)

    def create(self, job_id: str, kind: str, owner: str, params: dict[str, Any],
               idempotency_key: str) -> tuple[Job, bool]:
        """(job, created). If an equivalent live/succeeded job exists it is returned instead."""
        try:
            self._c.execute(
                "INSERT INTO job(job_id, kind, owner, status, created_at, idempotency_key, params)"
                " VALUES (?,?,?,?,?,?,?)",
                (job_id, kind, owner, QUEUED, self._clock(), idempotency_key,
                 json.dumps(params, sort_keys=True)))
            self._c.commit()
            self.append_event(job_id, "job_queued", {})
            return self.get(job_id), True  # type: ignore[return-value]
        except sqlite3.IntegrityError:
            self._c.rollback()
            row = self._c.execute(
                f"SELECT {_COLS} FROM job WHERE owner=? AND idempotency_key=? AND status IN "
                "('queued','running','succeeded') ORDER BY created_at DESC LIMIT 1",
                (owner, idempotency_key)).fetchone()
            if row is None:
                raise
            return _row_to_job(row), False

    def get(self, job_id: str) -> Job | None:
        row = self._c.execute(f"SELECT {_COLS} FROM job WHERE job_id=?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def list_for_owner(self, owner: str | None, limit: int, offset: int) -> list[Job]:
        q, args = f"SELECT {_COLS} FROM job", []
        if owner is not None:
            q, args = q + " WHERE owner=?", [owner]
        rows = self._c.execute(q + " ORDER BY created_at DESC, job_id LIMIT ? OFFSET ?",
                               [*args, limit, offset]).fetchall()
        return [_row_to_job(r) for r in rows]

    def mark_running(self, job_id: str) -> bool:
        cur = self._c.execute("UPDATE job SET status=?, started_at=? WHERE job_id=? AND status=?",
                              (RUNNING, self._clock(), job_id, QUEUED))
        self._c.commit()
        return cur.rowcount == 1

    def finish(self, job_id: str, status: str, *, error: str | None = None,
               outcome: str | None = None, category: str | None = None) -> None:
        assert status in TERMINAL
        self._c.execute("UPDATE job SET status=?, finished_at=?, error=?, outcome=?, category=? "
                        "WHERE job_id=? AND status IN ('queued','running')",
                        (status, self._clock(), error, outcome, category, job_id))
        self._c.commit()

    def request_cancel(self, job_id: str) -> Job | None:
        self._c.execute("UPDATE job SET cancel_requested=1 WHERE job_id=? AND status IN "
                        "('queued','running')", (job_id,))
        self._c.commit()
        return self.get(job_id)

    def cancel_requested(self, job_id: str) -> bool:
        row = self._c.execute("SELECT cancel_requested FROM job WHERE job_id=?",
                              (job_id,)).fetchone()
        return bool(row and row[0])

    def append_event(self, job_id: str, kind: str, payload: dict[str, Any]) -> int:
        body = json.dumps(payload, sort_keys=True, default=str)
        for _ in range(8):
            try:
                self._c.execute(
                    "INSERT INTO job_event(job_id, seq, ts, kind, payload) "
                    "SELECT ?, COALESCE(MAX(seq), 0) + 1, ?, ?, ? FROM job_event WHERE job_id=?",
                    (job_id, self._clock(), kind, body, job_id))
                self._c.commit()
                row = self._c.execute("SELECT MAX(seq) FROM job_event WHERE job_id=?",
                                      (job_id,)).fetchone()
                return int(row[0])
            except sqlite3.IntegrityError:
                self._c.rollback()  # lost a seq race with another writer: retry
        raise RuntimeError("could not append job event")

    def events_after(self, job_id: str, after_seq: int = 0, limit: int = 500
                     ) -> list[dict[str, Any]]:
        rows = self._c.execute(
            "SELECT seq, ts, kind, payload FROM job_event WHERE job_id=? AND seq>? "
            "ORDER BY seq LIMIT ?", (job_id, after_seq, limit)).fetchall()
        return [{"seq": r[0], "ts": r[1], "kind": r[2], "data": json.loads(r[3])} for r in rows]

    def recover_orphans(self) -> int:
        """Jobs left queued/running by a process that died can never finish: fail them visibly.
        Only safe when ONE process owns the database (the multi-instance fix is leases)."""
        ids = [r[0] for r in self._c.execute(
            "SELECT job_id FROM job WHERE status IN ('queued','running')").fetchall()]
        for jid in ids:
            self.finish(jid, FAILED, error="interrupted by a server restart")
            self.append_event(jid, "job_failed", {"error": "interrupted by a server restart"})
        return len(ids)


class JobExecutor(Protocol):
    def submit(self, fn: Callable[[], None]) -> None: ...
    def shutdown(self, wait: bool = True) -> None: ...


class InProcessExecutor:
    """Thread pool for development, tests and single-node deployments. A Celery executor
    implements the same two methods."""

    def __init__(self, max_workers: int = 2) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="akash-job")
        self._futures: list[Future[None]] = []
        self._lock = threading.Lock()

    def submit(self, fn: Callable[[], None]) -> None:
        with self._lock:
            self._futures = [f for f in self._futures if not f.done()]
            self._futures.append(self._pool.submit(fn))

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=not wait)
