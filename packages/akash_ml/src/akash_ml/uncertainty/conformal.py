"""Split-conformal prediction sets (class-conditional / Mondrian by default).

Guarantee (under exchangeability of calibration and new data): the true label is in the set with
probability >= 1 - alpha *for each class*. Sets can be {planet}, {not planet}, {both} (uncertain)
or {} (the model has no good answer: treat as out-of-distribution/abstain). The guarantee does
NOT hold under distribution shift (e.g. Kepler -> TESS); that is what the OOD flag is for.
"""

from __future__ import annotations

import math

import numpy as np
from akash_science.lightcurve.types import F64


class SplitConformal:
    def __init__(self, alpha: float = 0.1, class_conditional: bool = True) -> None:
        self.alpha, self.class_conditional = alpha, class_conditional
        self.qhat: dict[int, float] = {0: 1.0, 1: 1.0}

    @staticmethod
    def _score(p: F64, y: np.ndarray) -> F64:
        return np.asarray(1.0 - np.where(y == 1, p, 1.0 - p), dtype=np.float64)

    def fit(self, p_cal: F64, y_cal: np.ndarray) -> SplitConformal:
        s = self._score(p_cal, y_cal)
        groups = [0, 1] if self.class_conditional else [None]
        for g in groups:
            sg = s if g is None else s[y_cal == g]
            n = len(sg)
            if n == 0:
                q = 1.0
            else:
                k = math.ceil((n + 1) * (1 - self.alpha))
                q = 1.0 if k > n else float(np.sort(sg)[k - 1])
            for c in (0, 1) if g is None else (g,):
                self.qhat[c] = q
        return self

    def predict_sets(self, p: F64) -> np.ndarray:
        """(N, 2) boolean: column k True iff class k is in the prediction set."""
        in0 = p <= self.qhat[0]  # score if the true label were 0 is 1-(1-p) = p
        in1 = (1.0 - p) <= self.qhat[1]  # score if true label were 1: 1-p
        return np.stack([in0, in1], axis=1)


def coverage(y: np.ndarray, sets: np.ndarray) -> float:
    return float(sets[np.arange(len(y)), y.astype(int)].mean())


def class_coverage(y: np.ndarray, sets: np.ndarray) -> dict[int, float]:
    return {c: coverage(y[y == c], sets[y == c]) if (y == c).any() else float("nan")
            for c in (0, 1)}


def set_label(row: np.ndarray) -> str:
    if row[0] and row[1]:
        return "uncertain"
    if row[1]:
        return "planet_like"
    if row[0]:
        return "not_planet_like"
    return "abstain"
