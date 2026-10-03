"""quality -> normalise -> detrend -> upward clip -> BLS -> (re-detrend with transits masked,
re-search) -> views -> vetting. Deterministic: same input + config => identical output."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from akash_data.lightcurve import NormalizedLightCurve

from ..config import PipelineConfig
from .detrend import detrend_segments
from .quality import apply_quality, split_segments, upper_clip_mask
from .search import BLSSearcher, in_transit_mask
from .types import F64, TCE, StellarContext, VetContext, VetResult
from .vetting import run_checks
from .views import make_views


@dataclass
class TCEResult:
    tce: TCE
    vetting: list[VetResult]
    global_view: F64
    local_view: F64


@dataclass
class PipelineResult:
    config_hash: str
    version: str
    time: F64
    flux_norm: F64
    trend: F64
    flux_detrended: F64
    sigma: float
    noise_1h_ppm: float
    counts: dict[str, int]
    segments: list[tuple[float, float]]
    tces: list[TCEResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def noise_1h_ppm(time: F64, rel_resid: F64) -> float:
    """Robust scatter of 1-hour-binned residuals (CDPP-like proxy), ppm."""
    if len(time) < 10:
        return float("nan")
    b = np.floor((time - time[0]) * 24.0).astype(int)
    means = np.array([rel_resid[b == k].mean() for k in np.unique(b) if (b == k).sum() >= 3])
    if len(means) < 5:
        return float("nan")
    return float(1.4826 * np.median(np.abs(means - np.median(means))) * 1e6)


class LightCurvePipeline:
    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.cfg = config or PipelineConfig()

    def _empty(self, counts: dict[str, int], warning: str) -> PipelineResult:
        e = np.array([], dtype=np.float64)
        return PipelineResult(self.cfg.hash(), self.cfg.version, e, e, e, e, float("nan"),
                              float("nan"), counts, [], [], [warning])

    def run(self, lc: NormalizedLightCurve, stellar: StellarContext | None = None
            ) -> PipelineResult:
        cfg = self.cfg
        q = apply_quality(lc, cfg.quality)
        counts = dict(q.counts)
        segs = split_segments(q.time, cfg.quality.max_gap_days, cfg.quality.min_segment_points)
        if not segs:
            return self._empty(counts, "no usable segments")
        idx = np.concatenate([np.arange(s.start, s.stop) for s in segs])
        counts["dropped_short_segments"] = len(q.time) - len(idx)
        t, f = q.time[idx], q.flux[idx]
        csegs: list[slice] = []
        pos = 0
        for s in segs:
            csegs.append(slice(pos, pos + (s.stop - s.start)))
            pos += s.stop - s.start

        trend = detrend_segments(t, f, csegs, cfg.detrend)
        resid = f / trend
        keep, sigma = upper_clip_mask(resid, cfg.quality.upper_clip_sigma)
        counts["clipped_upward"] = int((~keep).sum())
        t, f, trend, resid = t[keep], f[keep], trend[keep], resid[keep]
        segs2 = split_segments(t, cfg.quality.max_gap_days, 1)
        edges = [(float(t[s.start]), float(t[s.stop - 1])) for s in segs2]

        tces = BLSSearcher(cfg.search).search(t, resid, sigma)
        searcher = BLSSearcher(cfg.search)
        if tces:  # re-detrend with the found transits masked so the filter can't eat them
            mask = np.zeros(len(t), dtype=bool)
            for c in tces:
                mask |= in_transit_mask(t, c.period_d, c.t0_bjd, 2.0 * c.duration_d)
            trend = detrend_segments(t, f, segs2, cfg.detrend, mask)
            resid = f / trend
            _, s2 = upper_clip_mask(resid[~mask], cfg.quality.upper_clip_sigma)
            sigma = s2 or sigma
            tces = searcher.search(t, resid, sigma)
        stats = searcher.last_stats

        results: list[TCEResult] = []
        for c, st in zip(tces, stats, strict=True):
            ctx = VetContext(t, resid, sigma, c, st, q.flagged_time, edges, stellar)
            g, loc = make_views(t, resid, c, cfg.view)
            results.append(TCEResult(c, run_checks(ctx), g, loc))
        warnings = [] if results else ["no threshold-crossing events found"]
        return PipelineResult(cfg.hash(), cfg.version, t, f, trend, resid, sigma,
                              noise_1h_ppm(t, resid - 1.0), counts, edges, results, warnings)
