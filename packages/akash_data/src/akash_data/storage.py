"""Content-addressed artifact store + SQLite metadata repository (dev default).

Artifacts are immutable and addressed by sha256. Re-ingesting the same bytes is a no-op.
Reads verify the hash, so silent corruption is detected rather than propagated.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from akash_core.errors import AkashError, ValidationFailure
from akash_core.ids import sha256_bytes
from akash_core.schemas import AstronomicalObject, CrossmatchLink, ObjectAlias, Observation

_ART_NS = uuid5(NAMESPACE_URL, "https://akash.invalid/artifact")


class IntegrityError(AkashError):
    """Stored bytes no longer match their content hash."""


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: UUID
    sha256: str
    uri: str
    size: int
    kind: str


def artifact_id_for(sha256: str) -> UUID:
    return uuid5(_ART_NS, sha256)


class LocalArtifactStore:
    def __init__(self, root: str | Path, conn: sqlite3.Connection) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._c = conn
        self._c.execute(
            "CREATE TABLE IF NOT EXISTS artifact (sha256 TEXT PRIMARY KEY, kind TEXT NOT NULL,"
            " size INTEGER NOT NULL, uri TEXT NOT NULL, quarantined INTEGER NOT NULL DEFAULT 0,"
            " quarantine_reason TEXT, created_at REAL NOT NULL)"
        )
        self._c.commit()

    def _path(self, sha: str) -> Path:
        return self.root / sha[:2] / sha

    def put(self, data: bytes, kind: str) -> ArtifactRef:
        sha = sha256_bytes(data)
        path = self._path(sha)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                os.replace(tmp, path)  # atomic
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        self._c.execute(
            "INSERT OR IGNORE INTO artifact(sha256,kind,size,uri,created_at) VALUES (?,?,?,?,?)",
            (sha, kind, len(data), path.resolve().as_uri(), time.time()),
        )
        self._c.commit()
        return ArtifactRef(artifact_id_for(sha), sha, path.resolve().as_uri(), len(data), kind)

    def get(self, sha: str) -> bytes:
        path = self._path(sha)
        if not path.exists():
            raise FileNotFoundError(sha)
        data = path.read_bytes()
        if sha256_bytes(data) != sha:
            raise IntegrityError(f"artifact {sha} failed hash verification")
        return data

    def exists(self, sha: str) -> bool:
        return self._path(sha).exists()

    def quarantine(self, sha: str, reason: str) -> None:
        self._c.execute(
            "UPDATE artifact SET quarantined=1, quarantine_reason=? WHERE sha256=?", (reason, sha)
        )
        self._c.commit()

    def is_quarantined(self, sha: str) -> tuple[bool, str | None]:
        row = self._c.execute(
            "SELECT quarantined, quarantine_reason FROM artifact WHERE sha256=?", (sha,)
        ).fetchone()
        if row is None:
            raise FileNotFoundError(sha)
        return bool(row[0]), row[1]


_REPO_SCHEMA = """
CREATE TABLE IF NOT EXISTS object (object_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alias (
  namespace TEXT NOT NULL, identifier TEXT NOT NULL, object_id TEXT NOT NULL REFERENCES object,
  payload TEXT NOT NULL, PRIMARY KEY (namespace, identifier));
CREATE TABLE IF NOT EXISTS crossmatch_link (
  object_id TEXT NOT NULL REFERENCES object, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS observation (
  obs_id TEXT PRIMARY KEY, object_id TEXT NOT NULL REFERENCES object, dataset TEXT NOT NULL,
  native_obs_id TEXT NOT NULL, modality TEXT NOT NULL, payload TEXT NOT NULL,
  UNIQUE (dataset, native_obs_id, object_id));
CREATE INDEX IF NOT EXISTS idx_obs_obj ON observation(object_id, modality);
CREATE TABLE IF NOT EXISTS query_cache (
  provider TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL, stored_at REAL NOT NULL,
  PRIMARY KEY (provider, key));
"""


class MetadataRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn
        self._c.execute("PRAGMA foreign_keys = ON")
        self._c.executescript(_REPO_SCHEMA)

    # ---- objects ----
    def save_object(self, obj: AstronomicalObject) -> None:
        self._c.execute(
            "INSERT OR REPLACE INTO object VALUES (?,?)",
            (str(obj.object_id), obj.model_dump_json()),
        )
        for a in obj.aliases:
            cur = self._c.execute(
                "SELECT object_id FROM alias WHERE namespace=? AND identifier=?",
                (a.namespace, a.identifier),
            ).fetchone()
            if cur and cur[0] != str(obj.object_id):
                raise ValidationFailure(
                    f"alias {a.namespace}/{a.identifier} already belongs to object {cur[0]}"
                )
            self._c.execute(
                "INSERT OR REPLACE INTO alias VALUES (?,?,?,?)",
                (a.namespace, a.identifier, str(obj.object_id), a.model_dump_json()),
            )
        self._c.commit()

    def get_object(self, object_id: UUID) -> AstronomicalObject | None:
        row = self._c.execute(
            "SELECT payload FROM object WHERE object_id=?", (str(object_id),)
        ).fetchone()
        return AstronomicalObject.model_validate_json(row[0]) if row else None

    def find_by_alias(self, namespace: str, identifier: str) -> AstronomicalObject | None:
        row = self._c.execute(
            "SELECT object_id FROM alias WHERE namespace=? AND identifier=?",
            (namespace.upper(), identifier),
        ).fetchone()
        return self.get_object(UUID(row[0])) if row else None

    def add_link(self, link: CrossmatchLink) -> None:
        self._c.execute(
            "INSERT INTO crossmatch_link VALUES (?,?)",
            (str(link.object_id), link.model_dump_json()),
        )
        self._c.commit()

    def links_for(self, object_id: UUID) -> list[CrossmatchLink]:
        rows = self._c.execute(
            "SELECT payload FROM crossmatch_link WHERE object_id=?", (str(object_id),)
        ).fetchall()
        return [CrossmatchLink.model_validate_json(r[0]) for r in rows]

    # ---- observations ----
    def save_observation(self, obs: Observation) -> None:
        self._c.execute(
            "INSERT OR REPLACE INTO observation VALUES (?,?,?,?,?,?)",
            (str(obs.obs_id), str(obs.object_id), obs.dataset, obs.native_obs_id,
             obs.modality.value, obs.model_dump_json()),
        )
        self._c.commit()

    def find_observation(
        self, object_id: UUID, dataset: str, native_obs_id: str
    ) -> Observation | None:
        row = self._c.execute(
            "SELECT payload FROM observation WHERE object_id=? AND dataset=? AND native_obs_id=?",
            (str(object_id), dataset, native_obs_id),
        ).fetchone()
        return Observation.model_validate_json(row[0]) if row else None

    def get_observation(self, obs_id: UUID) -> Observation | None:
        row = self._c.execute("SELECT payload FROM observation WHERE obs_id=?",
                              (str(obs_id),)).fetchone()
        return Observation.model_validate_json(row[0]) if row else None

    def list_observations(self, object_id: UUID, modality: str | None = None) -> list[Observation]:
        q = "SELECT payload FROM observation WHERE object_id=?"
        args: list[str] = [str(object_id)]
        if modality:
            q += " AND modality=?"
            args.append(modality)
        return [Observation.model_validate_json(r[0]) for r in self._c.execute(q, args)]

    # ---- query cache ----
    def cache_get(self, provider: str, key: str, ttl_s: float) -> object | None:
        row = self._c.execute(
            "SELECT payload, stored_at FROM query_cache WHERE provider=? AND key=?",
            (provider, key),
        ).fetchone()
        if row is None or time.time() - row[1] > ttl_s:
            return None
        value: object = json.loads(row[0])
        return value

    def cache_put(self, provider: str, key: str, value: object) -> None:
        self._c.execute(
            "INSERT OR REPLACE INTO query_cache VALUES (?,?,?,?)",
            (provider, key, json.dumps(value), time.time()),
        )
        self._c.commit()


__all__ = ["ArtifactRef", "IntegrityError", "LocalArtifactStore", "MetadataRepo", "ObjectAlias"]
