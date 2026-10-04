"""Process a light curve at a KNOWN ephemeris (period, t0, duration) instead of searching.

Used to build training views from catalog TCEs (as AstroNet did) and to evaluate candidates
whose ephemeris comes from elsewhere. Same quality/detrend/vetting code as the search path,
with the known transits masked out of the detrending fit.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from akash_data.lightcurve import NormalizedLightCurve

from ..config import PipelineConfig
from .detrend import detrend_segments
from .pipeline import noise_1h_ppm
from .quality import apply_quality, split_segments, upper_clip_mask
from .search import in_transit_mask, red_noise_beta
from .types import F64, TCE, StellarContext, VetContext, VetResult
from .vetting import run_checks
from .views import make_views


@dataclass
class EphemerisResult:
    tce: TCE
    vetting: list[VetResult]
    global_view: F64
    local_view: F64
    sigma: float
    noise_1h_ppm: float
    counts: dict[str, int]
    n_points: int


def stitch_lightcurves(lcs: list[NormalizedLightCurve]) -> NormalizedLightCurve:
    """Concatenate quarters/sectors, normalising each by its own median so that step offsets
    between segments do not leak into the detrender. Native quality flags are preserved."""
    if not lcs:
        raise ValueError("nothing to stitch")
    parts_t, parts_f, parts_e, parts_s, parts_q = [], [], [], [], []
    for lc in lcs:
        good = np.isfinite(lc.flux) & np.isfinite(lc.time_bjd) & (lc.native_quality == 0)
        med = float(np.median(lc.flux[good])) if good.any() else float(np.nanmedian(lc.flux))
        if not np.isfinite(med) or med <= 0:
            continue
        parts_t.append(lc.time_bjd)
        parts_f.append(lc.flux / med)
        parts_e.append(lc.flux_err / med)
        parts_s.append(lc.sap_flux / med)
        parts_q.append(lc.native_quality)
    if not parts_t:
        raise ValueError("no stitchable light curves")
    t = np.concatenate(parts_t)
    order = np.argsort(t, kind="stable")
    cat = [np.concatenate(p)[order] for p in (parts_f, parts_e, parts_s)]
    return NormalizedLightCurve(
        t[order], cat[0], cat[1], cat[2], np.concatenate(parts_q)[order],
        {"mission": lcs[0].meta.get("mission"), "n_stitched": len(lcs)})


def process_ephemeris(
    lc: NormalizedLightCurve, period_d: float, t0_bjd: float, duration_d: float,
    config: PipelineConfig | None = None, stellar: StellarContext | None = None,
) -> EphemerisResult | None:
    """Returns None when there is too little usable data to evaluate the ephemeris."""
    cfg = config or PipelineConfig()
    q = apply_quality(lc, cfg.quality)
    segs = split_segments(q.time, cfg.quality.max_gap_days, cfg.quality.min_segment_points)
    if not segs:
        return None
    idx = np.concatenate([np.arange(s.start, s.stop) for s in segs])
    t, f = q.time[idx], q.flux[idx]
    csegs, pos = [], 0
    for s in segs:
        csegs.append(slice(pos, pos + s.stop - s.start))
        pos += s.stop - s.start

    mask = in_transit_mask(t, period_d, t0_bjd, 2.0 * duration_d)  # keep the filter off transits
    trend = detrend_segments(t, f, csegs, cfg.detrend, mask)
    resid = f / trend
    keep, sigma = upper_clip_mask(resid, cfg.quality.upper_clip_sigma)
    t, resid, mask = t[keep], resid[keep], mask[keep]
    if sigma <= 0 or len(t) < 100:
        return None
    segs2 = split_segments(t, cfg.quality.max_gap_days, 1)
    edges = [(float(t[s.start]), float(t[s.stop - 1])) for s in segs2]

    ph = (t - t0_bjd + 0.5 * period_d) % period_d - 0.5 * period_d
    inn = np.abs(ph) <= 0.5 * duration_d
    if inn.sum() < 3:
        return None
    beta = red_noise_beta(t, resid - 1.0, duration_d, sigma, mask)
    depth = 1.0 - float(resid[inn].mean())
    snr = depth / (sigma * beta / np.sqrt(inn.sum()))
    cadence = float(np.median(np.diff(t)))
    epochs = np.round((t - t0_bjd) / period_d).astype(int)
    expected = max(duration_d / cadence, 1.0)
    times = [t0_bjd + int(k) * period_d for k in np.unique(epochs[inn])
             if (inn & (epochs == k)).sum() >= 0.5 * expected]
    tce = TCE(rank=1, period_d=period_d, period_interval_d=(period_d, period_d),
              t0_bjd=t0_bjd, duration_d=duration_d, depth_frac=depth, snr=float(snr), sde=0.0,
              n_transits=len(times), transit_times_bjd=times, beta=beta)
    ctx = VetContext(t, resid, sigma, tce, {}, q.flagged_time, edges, stellar)
    g, loc = make_views(t, resid, tce, cfg.view)
    return EphemerisResult(tce, run_checks(ctx), g, loc, sigma, noise_1h_ppm(t, resid - 1.0),
                           dict(q.counts), len(t))
