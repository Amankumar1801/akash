"""Identifier and hashing helpers. All hashing is deterministic and content-based."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID, uuid4


def new_id() -> UUID:
    return uuid4()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj: Any) -> str:
    """Stable JSON: sorted keys, no whitespace, so equal params hash equal."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def params_hash(obj: Any) -> str:
    return sha256_bytes(canonical_json(obj).encode("utf-8"))


def job_key(object_id: UUID, pipeline_version: str, params: dict[str, Any]) -> str:
    """Idempotency key: same object + pipeline version + params => same job/result."""
    return params_hash({"o": str(object_id), "v": pipeline_version, "p": params})
