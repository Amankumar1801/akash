"""Small, dependency-free statistics. Every rate is reported with an interval, never alone."""

from __future__ import annotations

import math

Z95 = 1.959964


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion. None when n == 0 (no data, no claim)."""
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def crossing(xs: list[float], ys: list[float], level: float) -> float | None:
    """Smallest x where the curve first reaches `level`, by linear interpolation between bins.
    None if it never does. The curve is noisy; callers must treat this as an estimate."""
    for i, y in enumerate(ys):
        if y >= level:
            if i == 0:
                return xs[0]
            x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], y
            return x0 if y1 == y0 else x0 + (level - y0) * (x1 - x0) / (y1 - y0)
    return None
