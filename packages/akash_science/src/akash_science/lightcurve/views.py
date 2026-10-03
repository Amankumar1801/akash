"""Phase-folded global/local views (AstroNet-style) for the classifier and for plotting."""

from __future__ import annotations

import numpy as np

from ..config import ViewConfig
from .types import F64, TCE


def _binned_median(x: F64, y: F64, lo: float, hi: float, nbins: int) -> F64:
    edges = np.linspace(lo, hi, nbins + 1)
    order = np.argsort(x)
    xs, ys = x[order], y[order]
    idx = np.searchsorted(xs, edges)
    out = np.full(nbins, np.nan)
    for i in range(nbins):
        a, b = idx[i], idx[i + 1]
        if b > a:
            out[i] = np.median(ys[a:b])
    ok = np.isfinite(out)
    if not ok.any():
        return np.zeros(nbins)
    centers = 0.5 * (edges[:-1] + edges[1:])
    out[~ok] = np.interp(centers[~ok], centers[ok], out[ok])  # fill empty bins
    return out


def fold_phase(time: F64, period: float, t0: float) -> F64:
    return np.asarray((time - t0 + 0.5 * period) % period - 0.5 * period, dtype=np.float64)


def make_views(time: F64, flux: F64, tce: TCE, cfg: ViewConfig) -> tuple[F64, F64]:
    """Return (global_view, local_view) as relative flux (flux - 1). Raw, not normalised."""
    ph = fold_phase(time, tce.period_d, tce.t0_bjd)
    rel = flux - 1.0
    g = _binned_median(ph, rel, -0.5 * tce.period_d, 0.5 * tce.period_d, cfg.global_bins)
    half = 0.5 * cfg.local_width_durations * tce.duration_d
    half = min(half, 0.5 * tce.period_d)
    sel = np.abs(ph) <= half
    loc = _binned_median(ph[sel], rel[sel], -half, half, cfg.local_bins) if sel.any() \
        else np.zeros(cfg.local_bins)
    return g, loc


def astronet_normalize(view: F64) -> F64:
    """Median -> 0, minimum -> -1 (AstroNet convention). Zero-depth views are returned centred."""
    v = view - np.median(view)
    m = float(-v.min())
    return v / m if m > 0 else v
