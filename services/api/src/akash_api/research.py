"""Stores for experiments and human review labels. Same SQLite connection as everything else."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, get_args

ExpStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
ReviewLabel = Literal["interesting", "not_interesting", "false_positive", "needs_followup",
                      "uncertain"]
LABELS: tuple[str, ...] = get_args(ReviewLabel)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiment (
  experiment_id TEXT PRIMARY KEY, owner TEXT NOT NULL, status TEXT NOT NULL,
  created_at REAL NOT NULL, started_at REAL, finished_at REAL, config TEXT NOT NULL,
  config_sha256 TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL,
  error TEXT, result TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_experiment_owner ON experiment(owner, created_at);
CREATE TABLE IF NOT EXISTS review_label (
  label_id INTEGER PRIMARY KEY AUTOINCREMENT, investigation_id TEXT NOT NULL,
  reviewer TEXT NOT NULL, label TEXT NOT NULL, note TEXT, triage_category TEXT,
  created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_label_inv ON review_label(investigation_id);
"""


@dataclass
class Experiment:
    experiment_id: str
    owner: str
    status: str
    created_at: float
    started_at: float | None
    finished_at: float | None
    config: dict[str, Any]
    config_sha256: str
    done: int
    total: int
    error: str | None
    result: dict[str, Any] | None
    cancel_requested: bool

    @property
    def terminal(self) -> bool:
        return self.status in ("succeeded", "failed", "cancelled")


_COLS = ("experiment_id, owner, status, created_at, started_at, finished_at, config, "
         "config_sha256, done, total, error, result, cancel_requested")


def _row(r: tuple[Any, ...]) -> Experiment:
    return Experiment(r[0], r[1], r[2], r[3], r[4], r[5], json.loads(r[6]), r[7], r[8], r[9],
                      r[10], json.loads(r[11]) if r[11] else None, bool(r[12]))


class ExperimentStore:
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time) -> None:
        self._c, self._clock = conn, clock
        self._c.executescript(_SCHEMA)

    def create(self, eid: str, owner: str, config: dict[str, Any], sha: str, total: int
               ) -> Experiment:
        self._c.execute("INSERT INTO experiment(experiment_id, owner, status, created_at, config,"
                        " config_sha256, total) VALUES (?,?,?,?,?,?,?)",
                        (eid, owner, "queued", self._clock(), json.dumps(config, sort_keys=True),
                         sha, total))
        self._c.commit()
        return self.get(eid)  # type: ignore[return-value]

    def get(self, eid: str) -> Experiment | None:
        r = self._c.execute(f"SELECT {_COLS} FROM experiment WHERE experiment_id=?",
                            (eid,)).fetchone()
        return _row(r) if r else None

    def list_for_owner(self, owner: str | None, limit: int) -> list[Experiment]:
        q, a = f"SELECT {_COLS} FROM experiment", []
        if owner is not None:
            q, a = q + " WHERE owner=?", [owner]
        return [_row(r) for r in self._c.execute(q + " ORDER BY created_at DESC LIMIT ?",
                                                 (*a, limit))]

    def active_count(self, owner: str) -> int:
        return int(self._c.execute("SELECT COUNT(*) FROM experiment WHERE owner=? AND status IN "
                                   "('queued','running')", (owner,)).fetchone()[0])

    def mark_running(self, eid: str) -> bool:
        cur = self._c.execute("UPDATE experiment SET status='running', started_at=? WHERE "
                              "experiment_id=? AND status='queued' AND cancel_requested=0",
                              (self._clock(), eid))
        self._c.commit()
        return cur.rowcount > 0

    def set_progress(self, eid: str, done: int) -> None:
        self._c.execute("UPDATE experiment SET done=? WHERE experiment_id=?", (done, eid))
        self._c.commit()

    def finish(self, eid: str, status: str, result: dict[str, Any] | None = None,
               error: str | None = None) -> None:
        self._c.execute("UPDATE experiment SET status=?, finished_at=?, result=?, error=? WHERE "
                        "experiment_id=?",
                        (status, self._clock(), json.dumps(result) if result else None, error,
                         eid))
        self._c.commit()

    def request_cancel(self, eid: str) -> None:
        self._c.execute("UPDATE experiment SET cancel_requested=1 WHERE experiment_id=?", (eid,))
        self._c.commit()

    def cancel_requested(self, eid: str) -> bool:
        r = self._c.execute("SELECT cancel_requested FROM experiment WHERE experiment_id=?",
                            (eid,)).fetchone()
        return bool(r and r[0])

    def recover_orphans(self) -> int:
        ids = [r[0] for r in self._c.execute(
            "SELECT experiment_id FROM experiment WHERE status IN ('queued','running')")]
        for i in ids:
            self.finish(i, "failed", error="interrupted by a server restart")
        return len(ids)


class LabelStore:
    """Append-only: a reviewer changing their mind adds a row; the latest row wins. History is
    what makes review quality (agreement, drift) measurable later."""

    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time) -> None:
        self._c, self._clock = conn, clock
        self._c.executescript(_SCHEMA)

    def add(self, investigation_id: str, reviewer: str, label: str, note: str | None,
            triage_category: str | None) -> int:
        if label not in LABELS:
            raise ValueError("unknown label")
        cur = self._c.execute(
            "INSERT INTO review_label(investigation_id, reviewer, label, note, triage_category, "
            "created_at) VALUES (?,?,?,?,?,?)",
            (investigation_id, reviewer, label, note, triage_category, self._clock()))
        self._c.commit()
        return int(cur.lastrowid or 0)

    def for_investigation(self, investigation_id: str) -> list[dict[str, Any]]:
        return [dict(zip(("label_id", "reviewer", "label", "note", "triage_category", "created_at"),
                         r, strict=True)) for r in self._c.execute(
            "SELECT label_id, reviewer, label, note, triage_category, created_at FROM review_label"
            " WHERE investigation_id=? ORDER BY label_id", (investigation_id,))]

    def export_latest(self) -> list[dict[str, Any]]:
        """Latest label per (investigation, reviewer): the unit an active-learning loop consumes."""
        q = ("SELECT investigation_id, reviewer, label, triage_category, created_at FROM "
             "review_label WHERE label_id IN (SELECT MAX(label_id) FROM review_label GROUP BY "
             "investigation_id, reviewer) ORDER BY label_id")
        return [dict(zip(("investigation_id", "reviewer", "label", "triage_category",
                          "created_at"), r, strict=True)) for r in self._c.execute(q)]
