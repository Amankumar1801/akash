"""API-key authentication with roles, plus an audit log.

Keys look like `akash_<key_id>_<secret>`. Only sha256(secret) is stored, looked up by the public
key_id and compared in constant time, so the database never holds a usable credential and lookup
timing does not leak the secret. (OIDC/OAuth is the production upgrade path.)"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_key (
  key_id TEXT PRIMARY KEY, secret_hash TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL,
  created_at REAL NOT NULL, revoked_at REAL);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, principal TEXT, action TEXT NOT NULL,
  resource TEXT, outcome TEXT NOT NULL, request_id TEXT);
"""


class Role(IntEnum):
    VIEWER = 1
    RESEARCHER = 2
    ADMIN = 3


ROLES = {r.name.lower(): r for r in Role}


@dataclass(frozen=True)
class Principal:
    key_id: str
    name: str
    role: Role

    def at_least(self, role: Role) -> bool:
        return self.role >= role


class ApiKeyStore:
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time) -> None:
        self._c, self._clock = conn, clock
        self._c.executescript(_SCHEMA)

    @staticmethod
    def _hash(secret: str) -> str:
        return hashlib.sha256(secret.encode()).hexdigest()

    def create(self, name: str, role: str) -> str:
        """Returns the full key ONCE; it cannot be recovered afterwards."""
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r}; expected one of {sorted(ROLES)}")
        key_id, secret = secrets.token_hex(4), secrets.token_urlsafe(32)
        self._c.execute("INSERT INTO api_key VALUES (?,?,?,?,?,NULL)",
                        (key_id, self._hash(secret), name, role, self._clock()))
        self._c.commit()
        return f"akash_{key_id}_{secret}"

    def verify(self, presented: str | None) -> Principal | None:
        if not presented or len(presented) > 200:
            return None
        parts = presented.split("_", 2)
        if len(parts) != 3 or parts[0] != "akash":
            return None
        row = self._c.execute(
            "SELECT secret_hash, name, role, revoked_at FROM api_key WHERE key_id=?",
            (parts[1],)).fetchone()
        stored = row[0] if row else "0" * 64  # compare anyway: no early exit on unknown key ids
        ok = hmac.compare_digest(stored, self._hash(parts[2]))
        if not row or not ok or row[3] is not None:
            return None
        return Principal(parts[1], row[1], ROLES[row[2]])

    def revoke(self, key_id: str) -> bool:
        cur = self._c.execute(
            "UPDATE api_key SET revoked_at=? WHERE key_id=? AND revoked_at IS NULL",
            (self._clock(), key_id))
        self._c.commit()
        return cur.rowcount > 0

    def audit(self, principal: str | None, action: str, resource: str | None, outcome: str,
              request_id: str | None) -> None:
        """Never pass credentials here."""
        self._c.execute("INSERT INTO audit_log(ts, principal, action, resource, outcome, "
                        "request_id) VALUES (?,?,?,?,?,?)",
                        (self._clock(), principal, action, resource, outcome, request_id))
        self._c.commit()

    def audit_entries(self, action: str | None = None) -> list[dict[str, str | None]]:
        q = "SELECT principal, action, resource, outcome, request_id FROM audit_log"
        args: tuple[str, ...] = ()
        if action:
            q, args = q + " WHERE action=?", (action,)
        return [dict(zip(("principal", "action", "resource", "outcome", "request_id"), r,
                         strict=True)) for r in self._c.execute(q + " ORDER BY id", args)]
