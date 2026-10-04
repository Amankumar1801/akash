"""Scalar feature vector for a TCE. Versioned: changing names/order requires a new version
because stored models depend on column order."""

from __future__ import annotations

import math

import numpy as np
from akash_science.lightcurve.ephemeris import EphemerisResult
from akash_science.lightcurve.types import F64

FEATURE_VERSION = "tf@1"
FEATURE_NAMES: tuple[str, ...] = (
    "log10_period_d", "log10_depth_ppm", "duration_hours", "duty_cycle", "log10_snr", "beta",
    "n_transits", "noise_1h_ppm", "odd_even_sigma", "secondary_sigma", "secondary_ratio",
    "shape_best_ingress", "shape_delta_chi2", "depth_chi2_red", "frac_overlap_flagged",
    "frac_near_edge", "duration_ratio", "implied_radius_rjup",
)
# the stellar-context features are NaN until Gaia/TIC parameters are supplied (Phase 5)
STELLAR_FEATURES = ("duration_ratio", "implied_radius_rjup")
CNN_SCALARS: tuple[str, ...] = FEATURE_NAMES[:8] + ("odd_even_sigma", "secondary_sigma")
_CLIP = {"odd_even_sigma": 50.0, "secondary_sigma": 50.0, "shape_delta_chi2": 500.0,
         "depth_chi2_red": 50.0, "secondary_ratio": 5.0}


def _metric(res: EphemerisResult, check: str, key: str) -> float:
    for v in res.vetting:
        if v.name == check:
            return float(v.metrics.get(key, math.nan))
    return math.nan


def features_from_ephemeris(res: EphemerisResult) -> F64:
    t = res.tce
    raw = {
        "log10_period_d": math.log10(t.period_d),
        "log10_depth_ppm": math.log10(max(t.depth_ppm, 1.0)),
        "duration_hours": t.duration_d * 24.0,
        "duty_cycle": t.duration_d / t.period_d,
        "log10_snr": math.log10(max(t.snr, 0.1)),
        "beta": t.beta, "n_transits": float(t.n_transits), "noise_1h_ppm": res.noise_1h_ppm,
        "odd_even_sigma": _metric(res, "odd_even", "sigma"),
        "secondary_sigma": _metric(res, "secondary_eclipse", "secondary_sigma"),
        "secondary_ratio": _metric(res, "secondary_eclipse", "ratio_to_primary"),
        "shape_best_ingress": _metric(res, "transit_shape", "best_ingress_fraction"),
        "shape_delta_chi2": _metric(res, "transit_shape", "delta_chi2_flat_minus_v"),
        "depth_chi2_red": _metric(res, "periodicity_coverage", "reduced_chi2_individual_depths"),
        "frac_overlap_flagged": _metric(res, "systematics_coincidence", "frac_overlap_flagged"),
        "frac_near_edge": _metric(res, "systematics_coincidence", "frac_near_segment_edge"),
        "duration_ratio": _metric(res, "duration_plausibility", "observed_over_expected"),
        "implied_radius_rjup": _metric(res, "depth_radius", "implied_radius_rjup"),
    }
    out = np.empty(len(FEATURE_NAMES), dtype=np.float64)
    for i, n in enumerate(FEATURE_NAMES):
        v = raw[n]
        if n in _CLIP and math.isfinite(v):
            v = float(np.clip(v, -_CLIP[n], _CLIP[n]))
        out[i] = v if math.isfinite(v) else math.nan
    return out
