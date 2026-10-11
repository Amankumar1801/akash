"""Min/max envelope downsampling for plotting: keeps every bucket's extremes (so transits and
flares survive) plus both endpoints, returning at most max_points indices in time order."""

from __future__ import annotations

import numpy as np


def minmax_indices(y: np.ndarray, max_points: int) -> np.ndarray:
    n = len(y)
    if n <= max_points:
        return np.arange(n)
    buckets = max((max_points - 2) // 2, 1)
    edges = np.linspace(0, n, buckets + 1).astype(int)
    keep = {0, n - 1}
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        if b <= a:
            continue
        seg = y[a:b]
        if np.isfinite(seg).any():
            keep.add(a + int(np.nanargmin(seg)))
            keep.add(a + int(np.nanargmax(seg)))
        else:
            keep.add(a)
    return np.array(sorted(keep))
