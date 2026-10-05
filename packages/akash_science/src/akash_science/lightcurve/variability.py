"""Variability, dip/flare and artifact metrics for anomaly detection. Deterministic, torch-free.

Everything is computed on the quality-filtered, median-normalised flux (NOT transit-detrended):
stellar variability is the signal here. A 1-day biweight residual is used only for dip/flare
statistics. Artifact metrics are computed alongside so the anomaly engine can tell "unusual star"
from "unusual instrument behaviour".
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from akash_data.lightcurve import NormalizedLightCurve
from astropy.timeseries import LombScargle

from ..config import DetrendConfig, QualityConfig
from .detrend import detrend_segments
from .pipeline import noise_1h_ppm
from .quality import apply_quality, split_segments
from .search import red_noise_beta
from .types import F64

VARIABILITY_VERSION = "var@3"
REP_LEN = 256
FEATURE_NAMES: tuple[str, ...] = (
    "log10_std_ppm", "log10_range_ppm", "skew", "kurtosis", "trend_ppm_per_day",
    "acf_1h", "acf_6h", "acf_24h", "ls_peak_power", "ls_log10_period", "ls_peak_ratio",
    "resid_log10_std_ppm", "resid_skew", "dip_fraction", "n_dips", "log10_deepest_dip_ppm",
    "n_slow_dips", "log10_deepest_slow_dip_ppm", "resid_ls_peak_power", "resid_ls_log10_period",
    "resid_short_period_power",
    "flare_fraction", "n_flares", "log10_max_flare_ppm", "log10_noise_1h_ppm", "log10_beta",
)
# Artifact thresholds: heuristic defaults. The anomaly engine replaces the ratio thresholds with
# percentiles of its reference population (adaptive); flagged_fraction stays absolute.
DEFAULT_ARTIFACT_THRESHOLDS = {
    "step_ratio": 3.0, "ramp_ratio": 3.0, "flagged_fraction": 0.20, "outlier_flag_overlap": 0.30,
}
STEP_WINDOW_D, RAMP_WINDOW_D = 1.5, 0.3

BIN_D = 1.0 / 48.0  # 30-minute bins for ACF / Lomb-Scargle
MIN_POINTS, MIN_BASELINE_D = 300, 5.0


class UnusableLightCurve(ValueError):
    """Too little usable data to characterise (carries the reason)."""


@dataclass
class VariabilityResult:
    features: F64
    representation: F64  # (REP_LEN,) median-subtracted, robust-scaled binned flux
    scale_ppm: float  # robust std used for the representation (amplitude is a feature too)
    quality: dict[str, float]
    artifact: dict[str, float]
    names: tuple[str, ...] = FEATURE_NAMES
    notes: list[str] = field(default_factory=list)


def _l10(x: float, floor: float = 1.0) -> float:
    return float(np.log10(max(x, floor)))


def _moments(x: F64) -> tuple[float, float]:
    s = x.std()
    if s <= 0:
        return 0.0, 0.0
    z = (x - x.mean()) / s
    return float((z**3).mean()), float((z**4).mean() - 3.0)


def _bin(t: F64, f: F64, width: float) -> tuple[F64, F64]:
    idx = np.floor((t - t[0]) / width).astype(int)
    uniq, start = np.unique(idx, return_index=True)
    ends = np.append(start[1:], len(idx))
    tb = np.array([t[a:b].mean() for a, b in zip(start, ends, strict=True)])
    fb = np.array([np.median(f[a:b]) for a, b in zip(start, ends, strict=True)])
    return tb, fb


def _acf_at(t: F64, f: F64, lag_bins: int) -> float:
    """ACF on the regular 30-min grid, using only pairs where both bins are populated."""
    n = int(round((t[-1] - t[0]) / BIN_D)) + 1
    grid = np.full(n, np.nan)
    grid[np.round((t - t[0]) / BIN_D).astype(int)] = f - np.mean(f)
    a, b = grid[:-lag_bins], grid[lag_bins:]
    ok = np.isfinite(a) & np.isfinite(b)
    var = np.nanmean(grid**2)
    return float(np.mean(a[ok] * b[ok]) / var) if ok.sum() > 10 and var > 0 else 0.0


def _runs(mask: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    out, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            if j - i + 1 >= min_len:
                out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def _lomb_scargle(tb: F64, fb: F64, baseline: float) -> tuple[float, float, float]:
    if len(tb) < 30:
        return 0.0, 1.0, 0.0
    ls = LombScargle(tb, fb - fb.mean())
    freq, power = ls.autopower(minimum_frequency=2.0 / baseline, maximum_frequency=4.0,
                                samples_per_peak=5)
    k = int(np.argmax(power))
    mask = np.abs(freq - freq[k]) > 0.1 * freq[k]
    second = float(power[mask].max()) if mask.any() else 0.0
    peak = float(power[k])
    return peak, float(np.log10(1.0 / freq[k])), (second / peak if peak > 0 else 0.0)


def _window_median(tb: F64, fb: F64, lo: float, hi: float) -> float | None:
    m = (tb >= lo) & (tb < hi)
    return float(np.median(fb[m])) if m.sum() >= max(3, int(0.3 * (hi - lo) / BIN_D)) else None


def _sf_p90(segs_b: list[tuple[F64, F64]], window: float, lag: float, floor: float) -> float:
    """90th percentile of |level change| between two windows `lag` apart, over the star's own
    interior. This is how much the star itself changes over that timescale."""
    diffs: list[float] = []
    for tb, fb in segs_b:
        s = tb[0]
        while s + lag + window <= tb[-1] + 1e-9:
            m1 = _window_median(tb, fb, s, s + window)
            m2 = _window_median(tb, fb, s + lag, s + lag + window)
            if m1 is not None and m2 is not None:
                diffs.append(abs(m2 - m1))
            s += window / 2.0
    return max(float(np.percentile(diffs, 90)), floor) if len(diffs) >= 5 else floor


def _step_and_ramp(segs_b: list[tuple[F64, F64]], floor_w: float, floor_r: float
                   ) -> tuple[float, float]:
    """step_ratio: persistent level offset across each data gap / the star's own change over the
    same lag. ramp_ratio: level change right at segment starts/ends / own change over that lag."""
    step = 0.0
    sf_gap_cache: dict[int, float] = {}
    for (t1, f1), (t2, f2) in zip(segs_b[:-1], segs_b[1:], strict=True):
        w = min(STEP_WINDOW_D, 0.4 * (t1[-1] - t1[0]), 0.4 * (t2[-1] - t2[0]))
        left = _window_median(t1, f1, t1[-1] - w, t1[-1] + 1e-9)
        right = _window_median(t2, f2, t2[0], t2[0] + w)
        if left is None or right is None or w < 0.5:
            continue
        lag = (t2[0] + w / 2) - (t1[-1] - w / 2)
        key = int(round(lag * 10))
        if key not in sf_gap_cache:
            sf_gap_cache[key] = _sf_p90(segs_b, w, lag, floor_w)
        step = max(step, abs(right - left) / sf_gap_cache[key])
    ramp = 0.0
    sf_r = _sf_p90(segs_b, RAMP_WINDOW_D, 2 * RAMP_WINDOW_D, floor_r)
    for tb, fb in segs_b:
        if tb[-1] - tb[0] < 4 * RAMP_WINDOW_D:
            continue
        pairs = [(_window_median(tb, fb, tb[0], tb[0] + RAMP_WINDOW_D),
                  _window_median(tb, fb, tb[0] + 2 * RAMP_WINDOW_D, tb[0] + 3 * RAMP_WINDOW_D)),
                 (_window_median(tb, fb, tb[-1] - RAMP_WINDOW_D, tb[-1] + 1e-9),
                  _window_median(tb, fb, tb[-1] - 3 * RAMP_WINDOW_D, tb[-1] - 2 * RAMP_WINDOW_D))]
        for m1, m2 in pairs:
            if m1 is not None and m2 is not None:
                ramp = max(ramp, abs(m1 - m2) / sf_r)
    return step, ramp


def _ls_band_power(tb: F64, fb: F64, pmin: float, pmax: float) -> float:
    """Peak Lomb-Scargle power restricted to periods in [pmin, pmax] days."""
    if len(tb) < 30 or tb[-1] - tb[0] < 3 * pmax:
        return 0.0
    ls = LombScargle(tb, fb - fb.mean())
    _, power = ls.autopower(minimum_frequency=1.0 / pmax, maximum_frequency=1.0 / pmin,
                            samples_per_peak=5)
    return float(power.max())


def extract_variability(lc: NormalizedLightCurve) -> VariabilityResult:
    qcfg = QualityConfig()
    q = apply_quality(lc, qcfg)
    segs = split_segments(q.time, qcfg.max_gap_days, 30)
    if not segs:
        raise UnusableLightCurve("no contiguous segments with >=30 usable cadences")
    idx = np.concatenate([np.arange(s.start, s.stop) for s in segs])
    t, f = q.time[idx], q.flux[idx]
    csegs, pos = [], 0
    for s in segs:
        csegs.append(slice(pos, pos + s.stop - s.start))
        pos += s.stop - s.start
    baseline = float(t[-1] - t[0])
    if len(t) < MIN_POINTS or baseline < MIN_BASELINE_D:
        raise UnusableLightCurve(
            f"{len(t)} points over {baseline:.1f} d is too little to characterise")

    cadence = float(np.median(np.diff(t)))
    rel = f - 1.0
    mad_std = float(1.4826 * np.median(np.abs(rel - np.median(rel))))
    skew, kurt = _moments(rel)
    slope = float(np.polyfit(t - t[0], rel, 1)[0]) * 1e6
    tb, fb = _bin(t, f, BIN_D)
    ls_peak, ls_logp, ls_ratio = _lomb_scargle(tb, fb, baseline)

    trend = detrend_segments(t, f, csegs, DetrendConfig(window_days=1.0))
    r = f / trend - 1.0
    sig = float(1.4826 * np.median(np.abs(r - np.median(r)))) or 1e-9
    z = r / sig
    dips, flares = _runs(z < -3.0, 2), _runs(z > 3.0, 2)
    deepest = max((-float(r[a:b + 1].mean()) * 1e6 for a, b in dips), default=0.0)
    max_flare = max((float(r[a:b + 1].max()) * 1e6 for a, b in flares), default=0.0)
    resid_skew = _moments(r)[0]
    # slow dips: a 4-day filter keeps day-long dimmings (Boyajian-like) that the 1-day filter eats
    rs = f / detrend_segments(t, f, csegs, DetrendConfig(window_days=4.0)) - 1.0
    sig_s = float(1.4826 * np.median(np.abs(rs - np.median(rs)))) or 1e-9
    slow = _runs(rs / sig_s < -3.0, max(int(round(0.1 / cadence)), 3))
    # periodicity of the RESIDUAL: fast periodic variability survives the 1-day filter, white
    # noise does not, so this separates "short-period variable" from "noisy"
    rtb, rfb = _bin(t, r, BIN_D)
    rl_peak, rl_logp, _ = _lomb_scargle(rtb, rfb, baseline)
    short_power = _ls_band_power(rtb, rfb, 0.25, 0.6)  # fast-pulsator-like periodicity
    deepest_slow = max((-float(rs[a:b + 1].mean()) * 1e6 for a, b in slow), default=0.0)
    noise1h = noise_1h_ppm(t, r)
    beta = red_noise_beta(t, r, 0.1, sig, np.zeros(len(t), dtype=bool))

    feats = np.array([
        _l10(mad_std * 1e6), _l10((np.percentile(rel, 95) - np.percentile(rel, 5)) * 1e6),
        skew, kurt, slope, _acf_at(tb, fb, 2), _acf_at(tb, fb, 12), _acf_at(tb, fb, 48),
        ls_peak, ls_logp, ls_ratio, _l10(sig * 1e6), resid_skew,
        float((z < -3.0).mean()), float(len(dips)), _l10(deepest),
        float(len(slow)), _l10(deepest_slow), rl_peak, rl_logp, short_power,
        float((z > 3.0).mean()), float(len(flares)), _l10(max_flare),
        _l10(noise1h) if np.isfinite(noise1h) else 0.0, _l10(beta, 0.5),
    ], dtype=np.float64)

    # ---- artifact metrics ----
    segs_b = [_bin(t[sl], f[sl], BIN_D) for sl in csegs]
    segs_b = [(tb_, fb_) for tb_, fb_ in segs_b if len(tb_) >= 10]
    n_per_win = STEP_WINDOW_D / BIN_D
    step_ratio, ramp_ratio = _step_and_ramp(
        segs_b, floor_w=3.0 * sig / np.sqrt(n_per_win),
        floor_r=3.0 * sig / np.sqrt(RAMP_WINDOW_D / BIN_D))
    flagged = q.flagged_time
    big = np.abs(z) > 5.0
    if big.any() and len(flagged):
        d = np.abs(t[big][:, None] - flagged[None, :]).min(axis=1)
        overlap = float((d <= 3.0 * cadence).mean())
    else:
        overlap = 0.0
    n_in = max(q.counts.get("input", len(t)), 1)
    artifact = {
        "step_ratio": float(step_ratio), "ramp_ratio": float(ramp_ratio),
        "flagged_fraction": float(q.counts.get("dropped_flagged", 0) / n_in),
        "outlier_flag_overlap": overlap,
    }

    # ---- fixed-length representation for the autoencoder ----
    edges = np.linspace(t[0], t[-1], REP_LEN + 1)
    rep = np.full(REP_LEN, np.nan)
    ix = np.clip(np.searchsorted(edges, t, side="right") - 1, 0, REP_LEN - 1)
    for k in np.unique(ix):
        rep[k] = np.median(f[ix == k])
    ok = np.isfinite(rep)
    cen = 0.5 * (edges[:-1] + edges[1:])
    rep[~ok] = np.interp(cen[~ok], cen[ok], rep[ok])
    rep = rep - np.median(rep)
    scale = max(float(1.4826 * np.median(np.abs(rep))), 1e-5)
    quality = {
        "n_points": float(len(t)), "baseline_d": baseline, "n_segments": float(len(csegs)),
        "unflagged_fraction": 1.0 - artifact["flagged_fraction"], "noise_1h_ppm": float(noise1h),
        "beta": float(beta), "cadence_s": cadence * 86400.0,
    }
    return VariabilityResult(feats, (rep / scale).astype(np.float32), scale * 1e6, quality,
                             artifact)


def assess_artifacts(m: dict[str, float], thresholds: dict[str, float] | None = None
                     ) -> tuple[bool, list[str]]:
    th = {**DEFAULT_ARTIFACT_THRESHOLDS, **(thresholds or {})}
    reasons = []
    if m["step_ratio"] >= th["step_ratio"]:
        reasons.append(f"persistent level offset across a data gap ({m['step_ratio']:.1f}x the "
                       "star's own variability at that lag)")
    if m["ramp_ratio"] >= th["ramp_ratio"]:
        reasons.append(f"ramp at a segment edge ({m['ramp_ratio']:.1f}x the star's own "
                       "variability)")
    if m["flagged_fraction"] >= th["flagged_fraction"]:
        reasons.append(f"{m['flagged_fraction']:.0%} of cadences quality-flagged")
    if m["outlier_flag_overlap"] >= th["outlier_flag_overlap"]:
        reasons.append(f"{m['outlier_flag_overlap']:.0%} of outliers sit next to flagged cadences")
    return bool(reasons), reasons
