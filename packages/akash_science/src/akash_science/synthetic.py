"""Synthetic light curves for tests and injection experiments.

CAVEAT: NOT real stellar noise (white + AR(1) red noise + sinusoidal variability). Injection
numbers measured on these show the pipeline behaves as designed; real-data sensitivity must be
measured on real light curves (Phase 10).
"""

from __future__ import annotations

import numpy as np
from akash_data.lightcurve import NormalizedLightCurve


def make_synthetic_lc(
    rng: np.random.Generator, days: float = 27.0, cadence_s: float = 600.0,
    noise_ppm: float = 800.0, red_ppm: float = 250.0, red_phi: float = 0.95,
    var_amp: float = 0.004, var_period_d: float = 4.7,
    gap: tuple[float, float] | None = (13.0, 14.2), flagged_frac: float = 0.01,
    t_start: float = 2458325.0,
) -> NormalizedLightCurve:
    n = int(days * 86400 / cadence_s)
    rel = np.arange(n) * cadence_s / 86400.0
    flux = (1.0 + var_amp * np.sin(2 * np.pi * rel / var_period_d + rng.uniform(0, 6.28))
            + 0.3 * var_amp * np.sin(2 * np.pi * rel / (var_period_d * 2.3)))
    innov = rng.normal(0, red_ppm * 1e-6 * np.sqrt(1 - red_phi**2), n)  # stationary AR(1)
    red = np.zeros(n)
    red[0] = rng.normal(0, red_ppm * 1e-6)
    for i in range(1, n):
        red[i] = red_phi * red[i - 1] + innov[i]
    flux = flux + red + rng.normal(0, noise_ppm * 1e-6, n)
    q = np.zeros(n, dtype=np.int32)
    q[rng.random(n) < flagged_frac] = 32
    keep = np.ones(n, dtype=bool)
    if gap:
        keep = ~((rel >= gap[0]) & (rel <= gap[1]))
    f = flux * 1000.0
    return NormalizedLightCurve(
        time_bjd=(t_start + rel)[keep], flux=f[keep],
        flux_err=np.full(int(keep.sum()), noise_ppm * 1e-3), sap_flux=f[keep] * 1.01,
        native_quality=q[keep], meta={"mission": "synthetic", "target_id": 0, "segment": 1},
    )
