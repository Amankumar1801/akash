"""Append-only evidence store + investigation records (SQLite; Postgres adapter later).
Evidence rows are never edited: a correction is a NEW row and the old one is marked superseded."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import UUID

from akash_core.errors import AkashError
from akash_core.schemas import Assessment, Evidence

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence (
  evidence_id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL, channel TEXT NOT NULL,
  payload TEXT NOT NULL, superseded_by TEXT);
CREATE INDEX IF NOT EXISTS idx_ev_inv ON evidence(investigation_id, channel);
CREATE TABLE IF NOT EXISTS investigation (
  investigation_id TEXT PRIMARY KEY, object_id TEXT NOT NULL, triage_category TEXT NOT NULL,
  created_at TEXT NOT NULL, payload TEXT NOT NULL);
"""


class EvidenceStoreError(AkashError):
    pass


class EvidenceStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn
        self._c.executescript(_SCHEMA)

    def save(self, assessment: Assessment | None, evidence: list[Evidence],
             investigation_id: UUID) -> None:
        with self._c:  # one transaction: an investigation is stored whole or not at all
            for e in evidence:
                self._c.execute("INSERT INTO evidence(evidence_id, investigation_id, channel, "
                                "payload) VALUES (?,?,?,?)",
                                (str(e.evidence_id), str(investigation_id), e.channel.value,
                                 e.model_dump_json()))
            if assessment is not None:
                self._c.execute(
                    "INSERT INTO investigation VALUES (?,?,?,?,?)",
                    (str(investigation_id), str(assessment.object_id),
                     assessment.triage_category.value, datetime.now(UTC).isoformat(),
                     assessment.model_dump_json()))

    def discard(self, investigation_id: UUID) -> None:
        """Remove what an interrupted attempt stored, so a retry starts clean."""
        with self._c:
            self._c.execute("DELETE FROM evidence WHERE investigation_id=?",
                            (str(investigation_id),))
            self._c.execute("DELETE FROM investigation WHERE investigation_id=?",
                            (str(investigation_id),))

    def get_assessment(self, investigation_id: UUID) -> Assessment | None:
        row = self._c.execute("SELECT payload FROM investigation WHERE investigation_id=?",
                              (str(investigation_id),)).fetchone()
        return Assessment.model_validate_json(row[0]) if row else None

    def list_evidence(self, investigation_id: UUID, channel: str | None = None,
                      include_superseded: bool = False) -> list[Evidence]:
        q = "SELECT payload, superseded_by FROM evidence WHERE investigation_id=?"
        args: list[str] = [str(investigation_id)]
        if channel:
            q += " AND channel=?"
            args.append(channel)
        out = []
        for payload, sup in self._c.execute(q, args):
            e = Evidence.model_validate_json(payload)
            if sup and not include_superseded:
                continue
            out.append(e.model_copy(update={"superseded_by": UUID(sup)}) if sup else e)
        return out

    def supersede(self, old_id: UUID, new: Evidence) -> None:
        """Replace a finding without editing it: store the new row, mark the old as superseded."""
        row = self._c.execute("SELECT investigation_id FROM evidence WHERE evidence_id=?",
                              (str(old_id),)).fetchone()
        if row is None:
            raise EvidenceStoreError(f"unknown evidence {old_id}")
        with self._c:
            self._c.execute("INSERT INTO evidence(evidence_id, investigation_id, channel, payload)"
                            " VALUES (?,?,?,?)", (str(new.evidence_id), row[0], new.channel.value,
                                                  new.model_dump_json()))
            self._c.execute("UPDATE evidence SET superseded_by=? WHERE evidence_id=?",
                            (str(new.evidence_id), str(old_id)))
