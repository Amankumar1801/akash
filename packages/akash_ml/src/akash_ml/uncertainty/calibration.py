"""Post-hoc probability calibration, fit on a held-out CALIBRATION split (never train/test)."""

from __future__ import annotations

from typing import Any

import numpy as np
from akash_science.lightcurve.types import F64
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

_EPS = 1e-6


def _logit(p: F64) -> F64:
    q = np.clip(p, _EPS, 1 - _EPS)
    return np.asarray(np.log(q / (1 - q)), dtype=np.float64)


class PlattCalibrator:
    method = "platt"

    def __init__(self, a: float = 1.0, b: float = 0.0) -> None:
        self.a, self.b = a, b

    def fit(self, p: F64, y: np.ndarray) -> PlattCalibrator:
        lr = LogisticRegression(C=1e6, max_iter=1000).fit(_logit(p).reshape(-1, 1), y)
        self.a, self.b = float(lr.coef_[0, 0]), float(lr.intercept_[0])
        return self

    def transform(self, p: F64) -> F64:
        z = self.a * _logit(p) + self.b
        return np.asarray(1 / (1 + np.exp(-z)), dtype=np.float64)

    def to_dict(self) -> dict[str, Any]:
        return {"method": self.method, "a": self.a, "b": self.b}


class IsotonicCalibrator:
    method = "isotonic"

    def __init__(self, xs: list[float] | None = None, ys: list[float] | None = None) -> None:
        self.xs, self.ys = xs or [0.0, 1.0], ys or [0.0, 1.0]

    def fit(self, p: F64, y: np.ndarray) -> IsotonicCalibrator:
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(p, y)
        self.xs = [float(v) for v in iso.X_thresholds_]
        self.ys = [float(v) for v in iso.y_thresholds_]
        return self

    def transform(self, p: F64) -> F64:
        return np.asarray(np.interp(p, self.xs, self.ys), dtype=np.float64)

    def to_dict(self) -> dict[str, Any]:
        return {"method": self.method, "xs": self.xs, "ys": self.ys}


def fit_calibrator(p: F64, y: np.ndarray,
                   method: str = "auto") -> PlattCalibrator | IsotonicCalibrator:
    """Isotonic needs data (it overfits small sets); default to Platt below ~1000 rows or when a
    class has < 100 examples."""
    if method == "auto":
        big = len(y) >= 1000 and min(int(y.sum()), int((1 - y).sum())) >= 100
        method = "isotonic" if big else "platt"
    return IsotonicCalibrator().fit(p, y) if method == "isotonic" else PlattCalibrator().fit(p, y)


def calibrator_from_dict(d: dict[str, Any]) -> PlattCalibrator | IsotonicCalibrator:
    if d["method"] == "platt":
        return PlattCalibrator(d["a"], d["b"])
    return IsotonicCalibrator(d["xs"], d["ys"])
