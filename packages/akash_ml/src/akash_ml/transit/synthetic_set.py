"""Labelled SYNTHETIC TCE set for testing the training/evaluation plumbing end to end.

Classes (label): planet (1) = flat-bottomed, consistent depths, no secondary; eclipsing binary
(0) = secondary eclipse / alternating depths / V-shaped; systematic (0) = periodic dips whose
individual depths vary wildly (instrumental-artifact-like); noise TCE (0) = best of many random
ephemerides on a signal-free curve (mimics the selection bias of a real search). Several TCEs
may share one star, so grouped splitting is exercised.

CAVEAT: metrics on this set validate the machinery, NOT science. Real training uses the Kepler
DR25 TCE table (see scripts/build_kepler_training_set.py).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from akash_data.lightcurve import NormalizedLightCurve
from akash_science.injection.models import InjectionSpec, inject
from akash_science.lightcurve.ephemeris import process_ephemeris
from akash_science.synthetic import make_synthetic_lc

from .dataset import TransitDataset
from .features import features_from_ephemeris

DAYS, CADENCE_S = 20.0, 1200.0


def _duration(p: float, rng: np.random.Generator) -> float:
    return float(13.0 / 24.0 * (p / 365.25) ** (1 / 3) * rng.uniform(0.6, 1.0))


def _noise_ephemeris(base: NormalizedLightCurve, rng: np.random.Generator
                     ) -> tuple[float, float, float]:
    """Pick the deepest-looking of 150 random ephemerides (selection bias like a real search)."""
    t, f = base.time_bjd, base.flux / np.median(base.flux)
    best, arg = -1.0, (3.0, float(t[0]), 0.1)
    for _ in range(150):
        p = float(np.exp(rng.uniform(np.log(1.0), np.log(8.0))))
        t0 = float(t[0] + rng.uniform(0, p))
        d = _duration(p, rng)
        ph = (t - t0 + 0.5 * p) % p - 0.5 * p
        inn = np.abs(ph) <= 0.5 * d
        if inn.sum() < 8:
            continue
        dip = (1.0 - f[inn].mean()) * np.sqrt(inn.sum())
        if dip > best:
            best, arg = float(dip), (p, t0, d)
    return arg


def _signal(kind: str, base: NormalizedLightCurve, rng: np.random.Generator
            ) -> tuple[list[InjectionSpec], tuple[float, float, float], int]:
    t0b = float(base.time_bjd[0])
    p = float(np.exp(rng.uniform(np.log(1.2), np.log(8.0))))
    t0 = t0b + float(rng.uniform(0.2, p))
    d = _duration(p, rng)
    if kind == "planet":
        depth = float(np.exp(rng.uniform(np.log(5e-4), np.log(8e-3))))
        return [InjectionSpec(p, t0, depth, d, 0.15)], (p, t0, d), 1
    if kind == "systematic":
        depth = float(np.exp(rng.uniform(np.log(1e-3), np.log(8e-3))))
        specs = []
        k = 0
        while t0 + k * p < t0b + DAYS:
            if rng.random() > 0.25:  # some events missing
                specs.append(InjectionSpec(1e4, t0 + k * p, depth * float(rng.uniform(0.2, 1.8)),
                                           d, 0.15))  # period 1e4 d => a single event
            k += 1
        return specs, (p, t0, d), 0
    if kind == "eb":
        depth = float(np.exp(rng.uniform(np.log(1.5e-3), np.log(2e-2))))
        style = rng.choice(["secondary", "alternating", "vshape"])
        if style == "secondary":
            sec = depth * float(rng.uniform(0.35, 1.0))
            return [InjectionSpec(p, t0, depth, d, 0.15),
                    InjectionSpec(p, t0 + 0.5 * p, sec, d, 0.15)], (p, t0, d), 0
        if style == "alternating":  # report the half period; odd/even depths differ
            half = 0.5 * p
            return [InjectionSpec(p, t0, depth, d, 0.15),
                    InjectionSpec(p, t0 + half, depth * float(rng.uniform(0.3, 0.7)), d, 0.15)
                    ], (half, t0, d), 0
        return [InjectionSpec(p, t0, depth, d * 1.3, 0.5)], (p, t0, d), 0
    return [], _noise_ephemeris(base, rng), 0


def make_synthetic_transit_dataset(n_stars: int, seed: int, id_offset: int = 0) -> TransitDataset:
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    for s in range(n_stars):
        base = make_synthetic_lc(rng, days=DAYS, cadence_s=CADENCE_S, gap=(9.0, 10.0))
        n_tce = int(rng.choice([1, 1, 2]))
        specs: list[InjectionSpec] = []
        eph: list[tuple[tuple[float, float, float], int]] = []
        for _ in range(n_tce):
            kind = str(rng.choice(["planet", "eb", "systematic", "noise"],
                                  p=[0.4, 0.25, 0.2, 0.15]))
            sig_specs, e, lab = _signal(kind, base, rng)
            specs += sig_specs
            eph.append((e, lab))
        f = base.flux
        for spec in specs:
            f = inject(base.time_bjd, f, spec)
        lc = NormalizedLightCurve(base.time_bjd, f, base.flux_err, base.sap_flux,
                                  base.native_quality, base.meta)
        star_id = id_offset + s + 1
        for k, ((p, t0, d), lab) in enumerate(eph):
            res = process_ephemeris(lc, p, t0, d)
            if res is None:
                continue
            rows.append(dict(star=star_id, tce=f"{star_id}.{k + 1}", label=lab, res=res))
    if not rows:
        raise RuntimeError("synthetic generation produced no TCEs")
    return TransitDataset(
        tce_ids=np.array([r["tce"] for r in rows]),
        star_ids=np.array([r["star"] for r in rows], dtype=np.int64),
        labels=np.array([r["label"] for r in rows], dtype=np.int8),
        global_views=np.stack([r["res"].global_view for r in rows]).astype(np.float32),
        local_views=np.stack([r["res"].local_view for r in rows]).astype(np.float32),
        features=np.stack([features_from_ephemeris(r["res"]) for r in rows]),
        meta={"snr": np.array([r["res"].tce.snr for r in rows]),
              "period_d": np.array([r["res"].tce.period_d for r in rows]),
              "depth_ppm": np.array([r["res"].tce.depth_ppm for r in rows])})
