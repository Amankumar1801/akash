"""Out-of-distribution flag: Mahalanobis distance of the scalar feature vector to the TRAINING
distribution, reported as a percentile of training distances."""

from __future__ import annotations

from typing import Any

import numpy as np
from akash_science.lightcurve.types import F64
from sklearn.covariance import LedoitWolf


class MahalanobisOOD:
    def __init__(self, columns: list[int], percentile_flag: float = 99.0) -> None:
        self.columns, self.percentile_flag = columns, percentile_flag
        self.median: F64 = np.zeros(len(columns))
        self.mean: F64 = np.zeros(len(columns))
        self.prec: F64 = np.eye(len(columns))
        self.train_d2: F64 = np.zeros(1)

    def _prep(self, x: F64) -> F64:
        z = x[:, self.columns].copy()
        bad = ~np.isfinite(z)
        z[bad] = np.broadcast_to(self.median, z.shape)[bad]
        return np.asarray(z, dtype=np.float64)

    def fit(self, x_train: F64) -> MahalanobisOOD:
        z = x_train[:, self.columns]
        self.median = np.nanmedian(z, axis=0)
        z = self._prep(x_train)
        lw = LedoitWolf().fit(z)  # shrinkage: stable with few rows / correlated features
        self.mean, self.prec = lw.location_, lw.precision_
        self.train_d2 = np.sort(self._d2(z))
        return self

    def _d2(self, z: F64) -> F64:
        d = z - self.mean
        return np.asarray(np.einsum("ij,jk,ik->i", d, self.prec, d), dtype=np.float64)

    def percentile(self, x: F64) -> F64:
        d2 = self._d2(self._prep(x))
        return np.asarray(np.searchsorted(self.train_d2, d2) / len(self.train_d2) * 100.0,
                          dtype=np.float64)

    def flag(self, x: F64) -> np.ndarray:
        return np.asarray(self.percentile(x) > self.percentile_flag)

    def to_dict(self) -> dict[str, Any]:
        return {"columns": self.columns, "percentile_flag": self.percentile_flag,
                "median": self.median.tolist(), "mean": self.mean.tolist(),
                "prec": self.prec.tolist(), "train_d2": self.train_d2.tolist()}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MahalanobisOOD:
        o = cls(d["columns"], d["percentile_flag"])
        o.median, o.mean = np.array(d["median"]), np.array(d["mean"])
        o.prec, o.train_d2 = np.array(d["prec"]), np.array(d["train_d2"])
        return o
