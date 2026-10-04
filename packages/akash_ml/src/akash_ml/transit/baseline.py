"""Trivial baseline the real models must beat: logistic regression on log10(SNR) alone."""

from __future__ import annotations

import numpy as np
from akash_science.lightcurve.types import F64
from sklearn.linear_model import LogisticRegression

from .dataset import TransitDataset
from .features import FEATURE_NAMES

_SNR = FEATURE_NAMES.index("log10_snr")


class SnrBaseline:
    family, version = "baseline_snr", "1"

    def __init__(self) -> None:
        self.lr = LogisticRegression()

    def fit(self, train: TransitDataset) -> SnrBaseline:
        self.lr.fit(train.features[:, [_SNR]], train.labels)
        return self

    def predict_proba(self, ds: TransitDataset) -> F64:
        return np.asarray(self.lr.predict_proba(ds.features[:, [_SNR]])[:, 1], dtype=np.float64)
