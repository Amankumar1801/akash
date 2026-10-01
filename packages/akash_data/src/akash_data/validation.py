from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from akash_core.errors import ValidationFailure

from .lightcurve import NormalizedLightCurve

# plausible cadences in seconds: TESS 20/120/200/600/1800, Kepler SC 58.85 / LC 1765.5
KNOWN_CADENCES_S = (20.0, 58.85, 120.0, 200.0, 600.0, 1765.5, 1800.0)
MIN_POINTS = 100
MIN_FINITE_FLUX_FRACTION = 0.5


@dataclass
class ValidationReport:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    def raise_if_failed(self) -> None:
        if not self.ok:
            raise ValidationFailure("; ".join(self.errors))


def validate_lightcurve(lc: NormalizedLightCurve) -> ValidationReport:
    r = ValidationReport()
    n = len(lc.time_bjd)
    r.metrics["n_points"] = float(n)
    if n < MIN_POINTS:
        r.errors.append(f"too few points ({n} < {MIN_POINTS})")
    if n:
        frac = float(np.isfinite(lc.flux).mean())
        r.metrics["finite_flux_fraction"] = frac
        if frac < MIN_FINITE_FLUX_FRACTION:
            r.errors.append(f"finite flux fraction {frac:.2f} < {MIN_FINITE_FLUX_FRACTION}")
        good = float((lc.native_quality == 0).mean())
        r.metrics["unflagged_fraction"] = good
        if good < 0.3:
            r.warnings.append(f"only {good:.0%} of cadences unflagged")
    if n >= 2:
        dt = np.diff(lc.time_bjd)
        if (dt < 0).any():
            r.errors.append("time is not monotonic")
        if (dt == 0).any():
            r.warnings.append("duplicate timestamps")
        cad = float(np.median(dt[dt > 0]) * 86400.0) if (dt > 0).any() else float("nan")
        r.metrics["median_cadence_s"] = cad
        if not any(abs(cad - k) / k < 0.1 for k in KNOWN_CADENCES_S):
            r.warnings.append(f"unusual cadence {cad:.1f}s")
    fe = lc.flux_err[np.isfinite(lc.flux_err)]
    if fe.size and (fe <= 0).any():
        r.warnings.append("non-positive flux errors present")
    r.ok = not r.errors
    return r
