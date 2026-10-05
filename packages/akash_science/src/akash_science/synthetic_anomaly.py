"""Synthetic populations for anomaly-detector development and evaluation.

CAVEAT: stand-ins, not real stars. "Normal" = diverse quasi-sinusoidal variables with white +
red noise and occasional small flares. Anomalies are injected with KNOWN labels so recovery can
be measured. Artifact kinds exist so the engine's ability to separate "unusual star" from
"unusual instrument" can be measured. Real-data evaluation is a Phase 10 task.
"""

from __future__ import annotations

import numpy as np
from akash_data.lightcurve import NormalizedLightCurve

from .synthetic import make_synthetic_lc

DAYS, CADENCE_S, GAP = 20.0, 1200.0, (9.0, 10.0)
INTERESTING = ("dimming", "flares", "extreme_amp", "unusual_period", "eclipsing")
ARTIFACTS = ("artifact_step", "artifact_flagged")
KINDS = ("normal", *INTERESTING, *ARTIFACTS)


def _flare(t: np.ndarray, t0: float, amp: float, decay_d: float) -> np.ndarray:
    dt = t - t0
    return np.where(dt >= 0, amp * np.exp(-np.clip(dt, 0, None) / decay_d), 0.0)


def _base(rng: np.random.Generator, **over: float) -> tuple[NormalizedLightCurve, np.ndarray]:
    kw = dict(
        var_amp=float(np.exp(rng.uniform(np.log(5e-4), np.log(8e-3)))),
        var_period_d=float(np.exp(rng.uniform(np.log(0.8), np.log(15.0)))),
        noise_ppm=float(np.exp(rng.uniform(np.log(300), np.log(1500)))),
        red_ppm=float(rng.uniform(50, 400)),
    )
    kw.update(over)
    lc = make_synthetic_lc(rng, days=DAYS, cadence_s=CADENCE_S, gap=GAP, **kw)
    return lc, lc.time_bjd - lc.time_bjd[0]


def _wrap(lc: NormalizedLightCurve, flux: np.ndarray,
          quality: np.ndarray | None = None) -> NormalizedLightCurve:
    return NormalizedLightCurve(lc.time_bjd, flux, lc.flux_err, lc.sap_flux,
                                lc.native_quality if quality is None else quality, lc.meta)


def make_lc(kind: str, rng: np.random.Generator) -> NormalizedLightCurve:
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    if kind == "extreme_amp":
        lc, rel = _base(rng, var_amp=float(rng.uniform(0.03, 0.08)))
    elif kind == "unusual_period":
        lc, rel = _base(rng, var_period_d=float(rng.uniform(0.3, 0.5)),
                        var_amp=float(rng.uniform(3e-3, 8e-3)))
    else:
        lc, rel = _base(rng)
    f = lc.flux / 1000.0  # back to ~1.0
    q = None
    if kind == "normal":
        for _ in range(int(rng.choice([0, 0, 1, 2]))):  # ordinary stars flare a little
            f = f + _flare(rel, float(rng.uniform(0, DAYS)), float(rng.uniform(2e-3, 8e-3)), 0.03)
    elif kind == "dimming":  # irregular, aperiodic, deep: Boyajian-like
        for _ in range(int(rng.integers(2, 5))):
            c, w = float(rng.uniform(1, DAYS - 1)), float(rng.uniform(0.3, 1.0))
            f = f - float(rng.uniform(0.01, 0.10)) * np.exp(-0.5 * ((rel - c) / w) ** 2)
    elif kind == "flares":
        for _ in range(int(rng.integers(15, 40))):
            f = f + _flare(rel, float(rng.uniform(0, DAYS)), float(rng.uniform(5e-3, 3e-2)),
                           float(rng.uniform(0.015, 0.04)))
    elif kind == "eclipsing":
        p = float(rng.uniform(1.0, 6.0))
        rng.uniform(0.03, 0.15)  # draw kept (value unused) so seeded populations stay reproducible
        ph = (rel - float(rng.uniform(0, 1)) + 0.5 * p) % p - 0.5 * p
        depth = float(rng.uniform(0.02, 0.15))
        f = f - depth * np.clip((0.06 * p - np.abs(ph)) / 0.02, 0, 1)
    elif kind == "artifact_step":
        after = rel > GAP[1]
        step = float(rng.choice([-1, 1])) * float(rng.uniform(0.015, 0.04))
        f = f * np.where(after, 1.0 + step, 1.0)
        for start in (0.0, GAP[1]):  # exponential ramps at segment starts
            ramp = float(rng.uniform(0.005, 0.02))
            f = f + ramp * np.exp(-np.clip(rel - start, 0, None) / 0.3) * (rel >= start)
    elif kind == "artifact_flagged":
        bad = rng.random(len(rel)) < float(rng.uniform(0.25, 0.4))
        q = np.where(bad, 32, 0).astype(np.int32)
        f = f + bad * rng.choice([-1, 1], len(rel)) * rng.uniform(0.01, 0.03, len(rel))
    return _wrap(lc, f * 1000.0, q)


def make_population(
    kind_counts: dict[str, int], seed: int,
) -> tuple[list[NormalizedLightCurve], list[str]]:
    rng = np.random.default_rng(seed)
    lcs, labels = [], []
    for kind, n in kind_counts.items():
        for _ in range(n):
            lcs.append(make_lc(kind, rng))
            labels.append(kind)
    return lcs, labels
