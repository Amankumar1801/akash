"""Stable seams. Every model family implements TransitModel; the council/ensemble layer only
sees these methods, so a new family (transformer, hybrid) plugs in without touching callers."""

from __future__ import annotations

from typing import Protocol

import numpy as np
from akash_science.lightcurve.types import F64

from .transit.dataset import TransitDataset


class TransitModel(Protocol):
    family: str  # "gbm" | "cnn1d" | ...
    version: str

    def predict_proba(self, ds: TransitDataset) -> F64:
        """RAW (uncalibrated) P(planet-like) per row, shape (N,)."""
        ...


class ProbCalibrator(Protocol):
    method: str

    def transform(self, p: F64) -> F64: ...


__all__ = ["ProbCalibrator", "TransitModel", "np"]
