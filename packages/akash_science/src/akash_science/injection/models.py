"""Injectable trapezoid transit model. (Limb-darkened batman models are a later upgrade;
trapezoids suffice for measuring sensitivity to depth/duration/period.)"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..lightcurve.types import F64


@dataclass(frozen=True)
class InjectionSpec:
    period_d: float
    t0_bjd: float
    depth_frac: float
    duration_d: float  # T14, first to fourth contact
    ingress_fraction: float = 0.1  # ingress length as a fraction of T14


def trapezoid_model(time: F64, spec: InjectionSpec) -> F64:
    """Multiplicative flux (1.0 out of transit)."""
    p, d = spec.period_d, spec.duration_d
    dt = np.abs((time - spec.t0_bjd + 0.5 * p) % p - 0.5 * p)
    ing = max(spec.ingress_fraction * d, 1e-12)
    shape = np.clip((0.5 * d - dt) / ing, 0.0, 1.0)
    return np.asarray(1.0 - spec.depth_frac * shape, dtype=np.float64)


def inject(time: F64, flux: F64, spec: InjectionSpec) -> F64:
    return np.asarray(flux * trapezoid_model(time, spec), dtype=np.float64)


def expected_snr(time: F64, sigma: float, spec: InjectionSpec) -> float:
    """Matched-filter SNR of the injected signal: sqrt(sum(((1-model)/sigma)^2)).
    Scales linearly with depth and 1/sigma; uses actual data coverage."""
    if sigma <= 0 or len(time) == 0:
        return 0.0
    signal = 1.0 - trapezoid_model(time, spec)
    return float(np.sqrt(np.sum((signal / sigma) ** 2)))
