"""Star-grouped, hash-based, frozen splits.

Why grouped: one star can host several TCEs; splitting by TCE puts siblings (same star, same
noise, same systematics) on both sides and inflates every metric. Why hash-based: a star's split
depends only on (salt, star_id), so it never changes when rows are added/removed -- the test set
stays frozen. The manifest hash lets CI detect accidental re-splitting.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
from akash_core.errors import ValidationFailure
from akash_core.ids import sha256_bytes

SPLIT_NAMES = ("train", "val", "calib", "test")
DEFAULT_FRACTIONS = {"train": 0.70, "val": 0.10, "calib": 0.10, "test": 0.10}


def _u01(salt: str, star_id: int) -> float:
    h = hashlib.sha256(f"{salt}:{int(star_id)}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64


def split_of(star_id: int, salt: str, fractions: dict[str, float] = DEFAULT_FRACTIONS) -> str:
    if abs(sum(fractions.values()) - 1.0) > 1e-9:
        raise ValueError("fractions must sum to 1")
    u, acc = _u01(salt, star_id), 0.0
    for name in SPLIT_NAMES:
        acc += fractions[name]
        if u < acc:
            return name
    return SPLIT_NAMES[-1]


@dataclass(frozen=True)
class SplitManifest:
    salt: str
    fractions: dict[str, float]
    assignment: dict[int, str]  # star_id -> split

    @classmethod
    def build(cls, star_ids: Iterable[int], salt: str,
              fractions: dict[str, float] = DEFAULT_FRACTIONS) -> SplitManifest:
        return cls(salt, dict(fractions),
                   {int(s): split_of(int(s), salt, fractions) for s in set(map(int, star_ids))})

    def digest(self) -> str:
        payload = json.dumps(sorted(self.assignment.items()), separators=(",", ":"))
        return sha256_bytes(f"{self.salt}|{payload}".encode())

    def counts(self) -> dict[str, int]:
        out = dict.fromkeys(SPLIT_NAMES, 0)
        for v in self.assignment.values():
            out[v] += 1
        return out

    def to_json(self) -> dict[str, Any]:
        return {"salt": self.salt, "fractions": self.fractions, "digest": self.digest(),
                "star_counts": self.counts(),
                "assignment": {str(k): v for k, v in sorted(self.assignment.items())}}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> SplitManifest:
        m = cls(d["salt"], d["fractions"], {int(k): v for k, v in d["assignment"].items()})
        if m.digest() != d["digest"]:
            raise ValidationFailure("split manifest digest mismatch: file was altered")
        return m

    def indices(self, star_ids: np.ndarray) -> dict[str, np.ndarray]:
        sp = np.array([self.assignment.get(int(s), "") for s in star_ids])
        if (sp == "").any():
            raise ValidationFailure("dataset contains stars absent from the split manifest")
        return {n: np.where(sp == n)[0] for n in SPLIT_NAMES}


def assert_no_leakage(star_ids: np.ndarray, parts: dict[str, np.ndarray]) -> None:
    """No star may appear in more than one split."""
    seen: dict[int, str] = {}
    for name, idx in parts.items():
        for s in set(map(int, star_ids[idx])):
            if s in seen and seen[s] != name:
                raise ValidationFailure(f"LEAKAGE: star {s} in both {seen[s]} and {name}")
            seen[s] = name
