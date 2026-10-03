"""Injection-recovery: inject known signals into base light curves, run the pipeline, score."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from akash_data.lightcurve import NormalizedLightCurve

from ..lightcurve.pipeline import LightCurvePipeline
from ..lightcurve.search import in_transit_mask, red_noise_beta
from ..lightcurve.types import TCE
from .models import InjectionSpec, expected_snr, inject

PERIOD_TOL = 0.01


@dataclass
class TrialResult:
    spec: InjectionSpec
    snr_expected: float
    recovered: bool
    alias: bool  # only an alias (P/2, 2P, P/3, 3P) was found
    found_period: float | None
    found_snr: float | None
    n_tces: int


def match_tce(tces: list[TCE], spec: InjectionSpec) -> tuple[bool, bool, int | None]:
    """(recovered at true period, alias-only, index of matching TCE).
    Epoch must line up with a true transit (mod the true period) within a duration."""
    alias = False
    for i, c in enumerate(tces):
        ratio = c.period_d / spec.period_d
        off = (c.t0_bjd - spec.t0_bjd + 0.5 * spec.period_d) % spec.period_d - 0.5 * spec.period_d
        if abs(off) > max(spec.duration_d, c.duration_d):
            continue
        if abs(ratio - 1.0) <= PERIOD_TOL:
            return True, False, i
        if any(abs(ratio - k) <= PERIOD_TOL for k in (0.5, 2.0, 1 / 3, 3.0)):
            alias = True
    return False, alias, None


def sample_specs(rng: np.random.Generator, n: int, t_start: float,
                 period_range: tuple[float, float], depth_range: tuple[float, float]
                 ) -> list[InjectionSpec]:
    """Periods and depths log-uniform; duration for a solar-density star times U(0.5, 1)
    (impact-parameter shortening). depth_range is in FRACTIONAL flux (1e-3 = 1000 ppm)."""
    out = []
    for _ in range(n):
        p = float(np.exp(rng.uniform(np.log(period_range[0]), np.log(period_range[1]))))
        d = float(np.exp(rng.uniform(np.log(depth_range[0]), np.log(depth_range[1]))))
        dur = float(13.0 / 24.0 * (p / 365.25) ** (1 / 3) * rng.uniform(0.5, 1.0))
        out.append(InjectionSpec(p, t_start + float(rng.uniform(0, p)), d, dur))
    return out


def run_trials(
    make_base: Callable[[np.random.Generator], NormalizedLightCurve],
    pipeline: LightCurvePipeline, n: int, seed: int,
    period_range: tuple[float, float] = (1.0, 10.0),
    depth_range: tuple[float, float] = (5e-4, 8e-3),
) -> list[TrialResult]:
    rng = np.random.default_rng(seed)
    out: list[TrialResult] = []
    for _ in range(n):
        base = make_base(rng)
        t = base.time_bjd
        spec = sample_specs(rng, 1, float(t[0]), period_range, depth_range)[0]
        lc = NormalizedLightCurve(t, inject(t, base.flux, spec), base.flux_err, base.sap_flux,
                                  base.native_quality, base.meta)
        res = pipeline.run(lc)
        snr = 0.0
        if len(res.time) and np.isfinite(res.sigma):
            beta = red_noise_beta(
                res.time, res.flux_detrended - 1.0, spec.duration_d, res.sigma,
                in_transit_mask(res.time, spec.period_d, spec.t0_bjd, 2.0 * spec.duration_d))
            snr = expected_snr(res.time, res.sigma * beta, spec)  # red-noise-inflated sigma
        ok, alias, idx = match_tce([r.tce for r in res.tces], spec)
        found = res.tces[idx].tce if idx is not None else None
        out.append(TrialResult(spec, snr, ok, alias and not ok,
                               found.period_d if found else None,
                               found.snr if found else None, len(res.tces)))
    return out


def run_controls(make_base: Callable[[np.random.Generator], NormalizedLightCurve],
                 pipeline: LightCurvePipeline, n: int, seed: int) -> tuple[int, int]:
    """(light curves yielding any TCE with no injection, n). Estimates the false-alarm rate
    ON SYNTHETIC NOISE ONLY."""
    rng = np.random.default_rng(seed)
    hits = sum(1 for _ in range(n) if pipeline.run(make_base(rng)).tces)
    return hits, n


def summarize_by_snr(results: list[TrialResult], edges: list[float]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        sel = [r for r in results if lo <= r.snr_expected < hi]
        n = len(sel)
        rows.append({
            "snr_lo": lo, "snr_hi": hi, "n": n,
            "recovered": sum(r.recovered for r in sel),
            "recovery_frac": sum(r.recovered for r in sel) / n if n else float("nan"),
            "alias_frac": sum(r.alias for r in sel) / n if n else float("nan"),
        })
    return rows
