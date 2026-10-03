"""Gap-aware sliding-window biweight detrending (Tukey), written in numpy.

The trend is evaluated on a coarse grid (window * grid_step_fraction) and interpolated; this is
~10-50x faster than per-point evaluation and loses nothing at scales below the window.
Points flagged in `mask` (e.g. in-transit) do not influence the trend but still receive a value.
"""

from __future__ import annotations

import numpy as np

from ..config import DetrendConfig
from .types import F64


def biweight_location(x: F64, c: float = 5.0, iterations: int = 5) -> float:
    m = float(np.median(x))
    for _ in range(iterations):
        mad = float(np.median(np.abs(x - m)))
        if mad == 0.0:
            break
        u = (x - m) / (c * mad)
        w = (1.0 - u * u) ** 2
        w[np.abs(u) >= 1.0] = 0.0
        s = float(w.sum())
        if s == 0.0:
            break
        m += float((w * (x - m)).sum() / s)
    return m


def biweight_trend(
    time: F64, flux: F64, cfg: DetrendConfig, mask: np.ndarray | None = None
) -> F64:
    """Trend for ONE contiguous segment. mask=True points are excluded from the estimate."""
    n = len(time)
    if n == 0:
        return np.array([], dtype=np.float64)
    use = np.ones(n, dtype=bool) if mask is None else ~mask
    tu, fu = time[use], flux[use]
    if len(tu) < cfg.min_window_points:
        return np.full(n, float(np.median(flux)), dtype=np.float64)
    half = cfg.window_days / 2.0
    step = max(cfg.window_days * cfg.grid_step_fraction, 1e-6)
    centers = np.arange(time[0], time[-1] + step, step)
    lo = np.searchsorted(tu, centers - half, side="left")
    hi = np.searchsorted(tu, centers + half, side="right")
    vals = np.full(len(centers), np.nan)
    for i, (a, b) in enumerate(zip(lo, hi, strict=True)):
        if b - a >= cfg.min_window_points:
            vals[i] = biweight_location(fu[a:b], cfg.biweight_c, cfg.iterations)
    ok = np.isfinite(vals)
    if not ok.any():
        return np.full(n, float(np.median(flux)), dtype=np.float64)
    return np.asarray(np.interp(time, centers[ok], vals[ok]), dtype=np.float64)


def detrend_segments(
    time: F64, flux: F64, segments: list[slice], cfg: DetrendConfig,
    mask: np.ndarray | None = None,
) -> F64:
    """Trend over all segments; never interpolates across segment gaps."""
    trend = np.full(len(time), np.nan, dtype=np.float64)
    for s in segments:
        m = None if mask is None else mask[s]
        trend[s] = biweight_trend(time[s], flux[s], cfg, m)
    return trend
