"""Explanations tied to the model's actual computation (never LLM-generated):
- GBM: SHAP values (LightGBM pred_contrib)
- CNN: occlusion -- slide a window across each view, replace it with the baseline, and measure the
  drop in predicted probability. Importance is mapped back to phase/time so it can be drawn on
  the light curve."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from akash_science.lightcurve.types import F64


def occlusion_importance(
    predict: Callable[[F64, F64], float], g: F64, loc: F64, g_win: int = 61, l_win: int = 11,
) -> tuple[F64, F64]:
    """Per-bin importance = mean over windows covering the bin of (p_full - p_occluded).
    Positive => that region SUPPORTS the prediction."""
    base = predict(g, loc)

    def run(view: F64, win: int, make: Callable[[F64], tuple[F64, F64]]) -> F64:
        n, fill = len(view), float(np.median(view))
        acc, cnt = np.zeros(n), np.zeros(n)
        stride = max(win // 2, 1)
        for a in range(0, n - win + 1, stride):
            v = view.copy()
            v[a:a + win] = fill
            drop = base - predict(*make(v))
            acc[a:a + win] += drop
            cnt[a:a + win] += 1
        return acc / np.maximum(cnt, 1)

    return run(g, g_win, lambda v: (v, loc)), run(loc, l_win, lambda v: (g, v))


def bins_to_windows(importance: F64, bin_centers: F64, k: int = 3, min_frac: float = 0.25
                    ) -> list[tuple[float, float, float]]:
    """Top-k contiguous regions of importance as (start, end, mean_importance) in axis units."""
    if importance.max() <= 0:
        return []
    hot = importance >= min_frac * importance.max()
    out, i, n = [], 0, len(hot)
    while i < n:
        if hot[i]:
            j = i
            while j + 1 < n and hot[j + 1]:
                j += 1
            out.append((float(bin_centers[i]), float(bin_centers[j]),
                        float(importance[i:j + 1].mean())))
            i = j + 1
        else:
            i += 1
    return sorted(out, key=lambda w: -w[2])[:k]
