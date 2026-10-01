from __future__ import annotations

import math


def propagate(
    ra_deg: float,
    dec_deg: float,
    pmra_mas_yr: float | None,
    pmdec_mas_yr: float | None,
    from_epoch: float,
    to_epoch: float,
) -> tuple[float, float]:
    """Linear proper-motion propagation. pmra is mu_alpha* (already includes cos(dec)).

    Adequate for matching at the arcsecond level over decades; not for astrometry.
    """
    if pmra_mas_yr is None or pmdec_mas_yr is None:
        return ra_deg, dec_deg
    dt = to_epoch - from_epoch
    dec = dec_deg + pmdec_mas_yr * dt / 3.6e6
    cosd = max(math.cos(math.radians(dec_deg)), 1e-6)
    ra = (ra_deg + pmra_mas_yr * dt / 3.6e6 / cosd) % 360.0
    return ra, dec


def angular_sep_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    a = math.sin((d2 - d1) / 2) ** 2 + math.cos(d1) * math.cos(d2) * math.sin((r2 - r1) / 2) ** 2
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(a)))) * 3600.0


def clear_winner(seps_sorted: list[float]) -> bool:
    """True if the nearest candidate is unambiguous.

    Tunable heuristic: a lone candidate wins; otherwise the runner-up must be at least 3x
    farther AND at least 2 arcsec farther than the best.
    """
    if len(seps_sorted) <= 1:
        return True
    best, second = seps_sorted[0], seps_sorted[1]
    return second >= max(3.0 * best, best + 2.0)
