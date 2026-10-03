from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from akash_data.lightcurve import NormalizedLightCurve

from ..config import QualityConfig
from .types import F64


@dataclass
class QualityResult:
    time: F64
    flux: F64  # normalised to median 1.0
    flux_err: F64
    flagged_time: F64  # times dropped because of native quality flags (kept for vetting)
    counts: dict[str, int] = field(default_factory=dict)
    median_flux: float = 1.0


def apply_quality(lc: NormalizedLightCurve, cfg: QualityConfig) -> QualityResult:
    t, f, e = lc.time_bjd, lc.flux, lc.flux_err
    q = lc.native_quality.astype(np.int64)
    flagged = (q & ~np.int64(cfg.allowed_quality_bits)) != 0
    finite = np.isfinite(t) & np.isfinite(f)
    keep = finite & ~flagged
    counts = {
        "input": int(len(t)),
        "dropped_flagged": int((flagged & finite).sum()),
        "dropped_nonfinite": int((~finite & ~flagged).sum()),
    }
    if not keep.any():
        empty = np.array([], dtype=np.float64)
        return QualityResult(empty, empty, empty, t[flagged].astype(np.float64), counts, 1.0)
    med = float(np.median(f[keep]))
    if med <= 0:
        raise ValueError("median flux is non-positive; cannot normalise")
    ee = np.where(np.isfinite(e), e, np.nan)
    return QualityResult(
        time=t[keep].astype(np.float64), flux=(f[keep] / med).astype(np.float64),
        flux_err=(ee[keep] / med).astype(np.float64),
        flagged_time=t[flagged].astype(np.float64), counts=counts, median_flux=med,
    )


def split_segments(time: F64, max_gap_days: float, min_points: int) -> list[slice]:
    """Contiguous runs separated by gaps > max_gap_days; runs shorter than min_points dropped."""
    if len(time) == 0:
        return []
    breaks = np.where(np.diff(time) > max_gap_days)[0] + 1
    edges = np.concatenate([[0], breaks, [len(time)]])
    return [slice(int(a), int(b)) for a, b in zip(edges[:-1], edges[1:], strict=True)
            if b - a >= min_points]


def upper_clip_mask(residual: F64, sigma_clip: float) -> tuple[np.ndarray, float]:
    """Boolean keep-mask removing only UPWARD outliers (never dips), and the robust sigma."""
    med = np.median(residual)
    sigma = float(1.4826 * np.median(np.abs(residual - med)))
    if sigma == 0:
        return np.ones(len(residual), dtype=bool), 0.0
    return residual <= med + sigma_clip * sigma, sigma
