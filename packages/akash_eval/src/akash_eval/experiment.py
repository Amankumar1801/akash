"""Injection-recovery experiment: configuration in, typed and auditable result out.

Known synthetic transits are injected into noise light curves, the real pipeline is run, and
recovery is scored. HONEST LIMIT: the default noise is synthetic (white + AR(1) + sinusoid), so
the curves show how the pipeline behaves on that noise, not real-survey sensitivity. The result
records the noise source so it cannot be mistaken for the latter."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Literal

import numpy as np
from akash_data.lightcurve import NormalizedLightCurve
from akash_science.injection.experiment import TrialResult, run_controls, run_trials
from akash_science.lightcurve.pipeline import LightCurvePipeline
from akash_science.synthetic import make_synthetic_lc
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .stats import crossing, wilson

MAX_TRIALS, MAX_CONTROLS = 60, 20
SNR_EDGES = [0.0, 7.0, 10.0, 15.0, 25.0, 50.0, 1e9]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExperimentConfig(_M):
    n_trials: int = Field(20, ge=4, le=MAX_TRIALS)
    n_controls: int = Field(6, ge=0, le=MAX_CONTROLS)
    seed: int = Field(0, ge=0, le=2**31 - 1)
    period_min_d: float = Field(1.0, ge=0.5, le=30.0)
    period_max_d: float = Field(10.0, ge=0.5, le=30.0)
    depth_min_ppm: float = Field(500.0, ge=50.0, le=50000.0)
    depth_max_ppm: float = Field(8000.0, ge=50.0, le=50000.0)
    noise_source: Literal["synthetic"] = "synthetic"

    @model_validator(mode="after")
    def _ordered(self) -> ExperimentConfig:
        if self.period_min_d >= self.period_max_d or self.depth_min_ppm >= self.depth_max_ppm:
            raise ValueError("ranges must be increasing")
        return self

    def key(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(), sort_keys=True).encode()).hexdigest()


class Rate(_M):
    k: int
    n: int
    rate: float | None
    lo: float | None
    hi: float | None


class Bin(_M):
    label: str
    lo: float
    hi: float
    recovered: Rate
    alias_only: Rate


class ExperimentResult(_M):
    config: ExperimentConfig
    config_sha256: str
    noise_note: str
    n_trials: int
    overall_recovery: Rate
    by_snr: list[Bin]
    by_period: list[Bin]
    by_depth: list[Bin]
    snr_at_50pct: float | None
    snr_at_90pct: float | None
    false_alarm: Rate | None  # light curves with NO injection that still yielded a candidate
    caveats: list[str]


def _rate(k: int, n: int) -> Rate:
    ci = wilson(k, n)
    return Rate(k=k, n=n, rate=(k / n if n else None), lo=ci[0] if ci else None,
                hi=ci[1] if ci else None)


def _bins(results: list[TrialResult], key: Callable[[TrialResult], float],
          edges: list[float], fmt: Callable[[float], str]) -> list[Bin]:
    out = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        sel = [r for r in results if lo <= key(r) < hi]
        out.append(Bin(label=f"{fmt(lo)} to {fmt(hi)}" if hi < 1e8 else f"{fmt(lo)} and above",
                       lo=lo, hi=hi, recovered=_rate(sum(r.recovered for r in sel), len(sel)),
                       alias_only=_rate(sum(r.alias for r in sel), len(sel))))
    return out


def summarise(cfg: ExperimentConfig, results: list[TrialResult],
              controls: tuple[int, int] | None) -> ExperimentResult:
    by_snr = _bins(results, lambda r: r.snr_expected, SNR_EDGES, lambda v: f"{v:g}")
    pe = [float(x) for x in np.geomspace(cfg.period_min_d, cfg.period_max_d, 4)]
    de = [float(x) for x in np.geomspace(cfg.depth_min_ppm, cfg.depth_max_ppm, 4)]
    pe[0], pe[-1] = pe[0] - 1e-9, pe[-1] + 1e-9
    de[0], de[-1] = de[0] - 1e-9, de[-1] + 1e-9
    usable = [b for b in by_snr if b.recovered.n >= 3]  # a bin of 1-2 trials is not a curve point
    xs = [b.lo for b in usable]
    ys = [b.recovered.rate or 0.0 for b in usable]
    return ExperimentResult(
        config=cfg, config_sha256=cfg.key(),
        noise_note="Noise is synthetic (white + AR(1) red noise + sinusoidal variability). "
                   "This measures pipeline behaviour on that noise, not real-survey sensitivity.",
        n_trials=len(results), overall_recovery=_rate(sum(r.recovered for r in results),
                                                      len(results)),
        by_snr=by_snr,
        by_period=_bins([*results], lambda r: r.spec.period_d, pe, lambda v: f"{v:.1f} d"),
        by_depth=_bins([*results], lambda r: r.spec.depth_frac * 1e6, de,
                       lambda v: f"{v:.0f} ppm"),
        snr_at_50pct=crossing(xs, ys, 0.5), snr_at_90pct=crossing(xs, ys, 0.9),
        false_alarm=_rate(*controls) if controls and controls[1] else None,
        caveats=[
            "Rates carry 95% Wilson intervals; with a few dozen trials they are wide.",
            "Recovery requires the true period and a matching epoch. Aliases (P/2, 2P, P/3, 3P) "
            "count as misses and are reported separately.",
            "SNR is the red-noise-inflated matched-filter SNR of the injected signal.",
            "The false-alarm rate is measured on noise-only synthetic curves.",
            "Injected transits are trapezoids, not limb-darkened planet models.",
        ])


class Cancelled(Exception):
    pass


def run_experiment(
    cfg: ExperimentConfig,
    make_base: Callable[[np.random.Generator], NormalizedLightCurve] | None = None,
    pipeline: LightCurvePipeline | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    chunk: int = 4,
) -> ExperimentResult:
    mk = make_base or (lambda g: make_synthetic_lc(g))
    pipe = pipeline or LightCurvePipeline()
    total = cfg.n_trials + cfg.n_controls
    done = 0
    results: list[TrialResult] = []
    # Trials run in chunks so progress and cancellation are responsive. Each chunk gets its own
    # derived seed, so the whole run is still deterministic for a given config.
    for i, start in enumerate(range(0, cfg.n_trials, chunk)):
        if cancelled and cancelled():
            raise Cancelled
        n = min(chunk, cfg.n_trials - start)
        results += run_trials(mk, pipe, n, seed=cfg.seed * 1000 + i,
                              period_range=(cfg.period_min_d, cfg.period_max_d),
                              depth_range=(cfg.depth_min_ppm * 1e-6, cfg.depth_max_ppm * 1e-6))
        done += n
        if progress:
            progress(done, total)
    controls: tuple[int, int] | None = None
    if cfg.n_controls:
        if cancelled and cancelled():
            raise Cancelled
        controls = run_controls(mk, pipe, cfg.n_controls, seed=cfg.seed * 1000 + 999)
        done += cfg.n_controls
        if progress:
            progress(done, total)
    return summarise(cfg, results, controls)
