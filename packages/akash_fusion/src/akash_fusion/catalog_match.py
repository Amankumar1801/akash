"""Does a detected signal correspond to something already in a catalog?

Matching is on PERIOD (the star may host other known entries while this signal is new). A match
inherits the catalog's disposition; AKASH reports it, never decides it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from akash_data.base import CatalogRecord

PERIOD_KEYS = {"toi": "pl_orbper", "cumulative": "koi_period"}
PERIOD_TOL = 0.01  # 1% fractional period agreement
HARMONICS = ((1.0, "exact"), (2.0, "harmonic_2x"), (0.5, "harmonic_0.5x"))


@dataclass(frozen=True)
class CatalogMatch:
    record: CatalogRecord
    status: str  # confirmed | candidate | false_positive
    catalog_period_d: float
    relation: str  # exact | harmonic_2x | harmonic_0.5x
    rel_diff: float


def record_period(rec: CatalogRecord) -> float | None:
    key = PERIOD_KEYS.get(rec.table)
    v: Any = rec.values.get(key) if key else None
    try:
        p = float(v)
    except (TypeError, ValueError):
        return None
    return p if p > 0 and p == p else None


def match_signal(period_d: float, records: list[CatalogRecord],
                 tol: float = PERIOD_TOL) -> CatalogMatch | None:
    """Best match by smallest fractional difference; an exact-period match beats a harmonic one
    at equal difference."""
    best: CatalogMatch | None = None
    for rec in records:
        cp, status = record_period(rec), rec.status
        if cp is None or status is None:
            continue
        for factor, relation in HARMONICS:
            diff = abs(period_d * factor - cp) / cp
            if diff <= tol and (best is None or (diff, relation != "exact") <
                                (best.rel_diff, best.relation != "exact")):
                best = CatalogMatch(rec, status, cp, relation, diff)
    return best


def star_entry_summary(records: list[CatalogRecord]) -> dict[str, int]:
    out = {"confirmed": 0, "candidate": 0, "false_positive": 0, "unclassified": 0}
    for r in records:
        out[r.status if r.status in out else "unclassified"] += 1
    return out
