"""SQLite-backed provenance store (dev/test default; a Postgres adapter follows in Phase 6).

Edge semantics: edge(from, to, wasDerivedFrom) means `from` was derived from `to`.
Lineage = all transitive ancestors reachable by following edges from -> to.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from uuid import UUID

from akash_core.enums import ProvRelation
from akash_core.errors import AkashError
from akash_core.schemas import ProvenanceRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prov_record (
  prov_id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, activity TEXT NOT NULL,
  code_version TEXT NOT NULL, sha256 TEXT, source_uri TEXT, dataset TEXT, release TEXT,
  at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prov_edge (
  from_prov TEXT NOT NULL REFERENCES prov_record(prov_id),
  to_prov TEXT NOT NULL REFERENCES prov_record(prov_id),
  relation TEXT NOT NULL,
  PRIMARY KEY (from_prov, to_prov, relation)
);
CREATE INDEX IF NOT EXISTS idx_prov_edge_from ON prov_edge(from_prov);
"""


class ProvenanceError(AkashError):
    pass


class SqliteProvenanceStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn
        self._c.row_factory = sqlite3.Row
        self._c.execute("PRAGMA foreign_keys = ON")
        self._c.executescript(_SCHEMA)

    def add(self, rec: ProvenanceRecord) -> ProvenanceRecord:
        self._c.execute(
            "INSERT INTO prov_record VALUES (?,?,?,?,?,?,?,?,?)",
            (
                str(rec.prov_id), rec.entity_type, rec.activity, rec.code_version,
                rec.sha256, rec.source_uri, rec.dataset, rec.release, rec.at.isoformat(),
            ),
        )
        self._c.commit()
        return rec

    def link(self, from_id: UUID, to_id: UUID, relation: ProvRelation) -> None:
        self._c.execute(
            "INSERT OR IGNORE INTO prov_edge VALUES (?,?,?)",
            (str(from_id), str(to_id), relation.value),
        )
        self._c.commit()

    def get(self, prov_id: UUID) -> ProvenanceRecord:
        row = self._c.execute(
            "SELECT * FROM prov_record WHERE prov_id=?", (str(prov_id),)
        ).fetchone()
        if row is None:
            raise ProvenanceError(f"unknown provenance id {prov_id}")
        return _row_to_record(row)

    def lineage(self, prov_id: UUID) -> list[ProvenanceRecord]:
        """All transitive ancestors of prov_id (excluding itself), oldest first."""
        rows = self._c.execute(
            """
            WITH RECURSIVE anc(id) AS (
              SELECT to_prov FROM prov_edge WHERE from_prov = ?
              UNION
              SELECT e.to_prov FROM prov_edge e JOIN anc ON e.from_prov = anc.id
            )
            SELECT r.* FROM prov_record r JOIN anc ON r.prov_id = anc.id ORDER BY r.at
            """,
            (str(prov_id),),
        ).fetchall()
        return [_row_to_record(r) for r in rows]

    def verify_chain(self, prov_id: UUID) -> None:
        """Raise unless the chain bottoms out in a root with a source URI and content hash."""
        rec = self.get(prov_id)
        chain = [rec, *self.lineage(prov_id)]
        roots = [r for r in chain if not self._has_parents(r.prov_id)]
        if not roots:
            raise ProvenanceError("cyclic or empty provenance chain")
        for r in roots:
            if not r.source_uri or not r.sha256:
                raise ProvenanceError(
                    f"root {r.prov_id} ({r.activity}) lacks source_uri/sha256: chain unverifiable"
                )

    def _has_parents(self, prov_id: UUID) -> bool:
        return (
            self._c.execute(
                "SELECT 1 FROM prov_edge WHERE from_prov=? LIMIT 1", (str(prov_id),)
            ).fetchone()
            is not None
        )


def _row_to_record(row: sqlite3.Row) -> ProvenanceRecord:
    return ProvenanceRecord(
        prov_id=UUID(row["prov_id"]), entity_type=row["entity_type"], activity=row["activity"],
        code_version=row["code_version"], sha256=row["sha256"], source_uri=row["source_uri"],
        dataset=row["dataset"], release=row["release"], at=datetime.fromisoformat(row["at"]),
    )
