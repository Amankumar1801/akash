from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt
from akash_core.enums import VetStatus

F64 = npt.NDArray[np.float64]


@dataclass(frozen=True)
class StellarContext:
    """Optional stellar properties (from Gaia/TIC, supplied in Phase 5). None => check UNKNOWN."""

    radius_rsun: float | None = None
    logg: float | None = None

    @property
    def density_solar(self) -> float | None:
        # rho/rho_sun = g/g_sun / R (since g ~ M/R^2 and rho ~ M/R^3); logg_sun = 4.438
        if self.radius_rsun is None or self.logg is None or self.radius_rsun <= 0:
            return None
        return float(10 ** (self.logg - 4.438) / self.radius_rsun)


@dataclass
class TCE:
    """Threshold-crossing event: a periodic dip candidate. Not a planet claim."""

    rank: int
    period_d: float
    period_interval_d: tuple[float, float]  # approx 1-sigma from delta-logL = 0.5 (heuristic)
    t0_bjd: float
    duration_d: float
    depth_frac: float
    snr: float
    sde: float
    n_transits: int
    transit_times_bjd: list[float] = field(default_factory=list)
    beta: float = 1.0  # red-noise inflation factor applied to SNR/errors (>= 1)

    @property
    def depth_ppm(self) -> float:
        return self.depth_frac * 1e6


@dataclass(frozen=True)
class VetResult:
    name: str
    status: VetStatus
    summary: str
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass
class VetContext:
    time: F64  # detrended, quality-filtered
    flux: F64  # detrended, ~1.0
    sigma: float  # robust per-point scatter
    tce: TCE
    stats: dict[str, Any]  # astropy BLS compute_stats output
    flagged_time: F64  # times of cadences dropped for native quality flags
    segment_edges: list[tuple[float, float]]  # (start, end) of each contiguous segment
    stellar: StellarContext | None = None
