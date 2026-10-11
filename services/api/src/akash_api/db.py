"""One SQLite connection per request/job (never shared across threads), WAL + busy timeout so
the API, job workers and SSE readers coexist. A Postgres adapter replaces this in production."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from akash_data.storage import LocalArtifactStore, MetadataRepo
from akash_fusion.store import EvidenceStore
from akash_provenance import SqliteProvenanceStore


def open_connection(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@dataclass
class StoreContext:
    conn: sqlite3.Connection
    repo: MetadataRepo
    prov: SqliteProvenanceStore
    artifacts: LocalArtifactStore
    evidence: EvidenceStore

    def close(self) -> None:
        self.conn.close()


def make_store_context(db_path: str, artifacts_dir: str) -> StoreContext:
    conn = open_connection(db_path)
    return StoreContext(conn, MetadataRepo(conn), SqliteProvenanceStore(conn),
                        LocalArtifactStore(artifacts_dir, conn), EvidenceStore(conn))
