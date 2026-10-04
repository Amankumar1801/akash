"""Data-quality grade for a TCE evaluation. Heuristic, rule-based, and independent of the
model's probability (a confident model on poor data is still poor data)."""

from __future__ import annotations

from akash_core.enums import QualityGrade
from akash_core.schemas import DataQuality

_ORDER = [QualityGrade.A, QualityGrade.B, QualityGrade.C, QualityGrade.D]


def grade_quality(snr: float, n_transits: int, beta: float, dropped_fraction: float,
                  noise_1h_ppm: float | None = None) -> DataQuality:
    reasons: list[str] = []
    if snr >= 12 and n_transits >= 6:
        g = 0
    elif snr >= 9 and n_transits >= 4:
        g = 1
    elif snr >= 7.1 and n_transits >= 3:
        g = 2
    else:
        g = 3
        reasons.append(f"low signal (SNR {snr:.1f}, {n_transits} transits)")
    if beta > 2.0:
        g = min(g + 1, 3)
        reasons.append(f"strong correlated noise (beta={beta:.1f})")
    if dropped_fraction > 0.3:
        g = min(g + 1, 3)
        reasons.append(f"{dropped_fraction:.0%} of cadences dropped")
    if n_transits < 3 and "low signal" not in " ".join(reasons):
        reasons.append(f"only {n_transits} transits")
    return DataQuality(grade=_ORDER[g], reasons=reasons)
