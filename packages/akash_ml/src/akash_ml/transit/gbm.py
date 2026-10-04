"""LightGBM classifier on scalar features. CPU-only, fast, SHAP-native (pred_contrib)."""

from __future__ import annotations

from typing import Any

import lightgbm as lgb
import numpy as np
from akash_science.lightcurve.types import F64

from ..metrics import pr_auc
from .dataset import TransitDataset
from .features import FEATURE_NAMES

DEFAULT_PARAMS: dict[str, Any] = {
    "objective": "binary", "learning_rate": 0.05, "num_leaves": 15, "min_data_in_leaf": 8,
    "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 1.0,
    "verbosity": -1, "num_threads": 1, "deterministic": True, "force_row_wise": True,
}


class GBMTransitModel:
    family = "gbm"

    def __init__(self, booster: lgb.Booster | None = None, version: str = "gbm@1",
                 seed: int = 0) -> None:
        self.booster, self.version, self.seed = booster, version, seed

    def fit(self, train: TransitDataset, val: TransitDataset, rounds: int = 600,
            patience: int = 40) -> GBMTransitModel:
        params = {**DEFAULT_PARAMS, "seed": self.seed}
        n_pos = max(int(train.labels.sum()), 1)
        params["scale_pos_weight"] = float((len(train) - n_pos) / n_pos)  # class imbalance
        dtr = lgb.Dataset(train.features, train.labels, feature_name=list(FEATURE_NAMES))
        dva = lgb.Dataset(val.features, val.labels, reference=dtr)
        self.booster = lgb.train(
            params, dtr, rounds, valid_sets=[dva],
            callbacks=[lgb.early_stopping(patience, verbose=False)])
        return self

    def predict_proba(self, ds: TransitDataset) -> F64:
        assert self.booster is not None, "model not fitted"
        return np.asarray(self.booster.predict(ds.features), dtype=np.float64)

    def contributions(self, ds: TransitDataset) -> F64:
        """SHAP values in log-odds space, shape (N, F+1); the last column is the base value."""
        assert self.booster is not None
        return np.asarray(self.booster.predict(ds.features, pred_contrib=True), dtype=np.float64)

    def top_features(self, ds: TransitDataset, row: int, k: int = 5) -> list[tuple[str, float]]:
        c = self.contributions(ds.subset(np.array([row])))[0, :-1]
        order = np.argsort(-np.abs(c))[:k]
        return [(FEATURE_NAMES[i], float(c[i])) for i in order]

    def to_string(self) -> str:
        assert self.booster is not None
        return str(self.booster.model_to_string())

    @classmethod
    def from_string(cls, s: str, version: str = "gbm@1") -> GBMTransitModel:
        return cls(lgb.Booster(model_str=s), version)

    def val_pr_auc(self, val: TransitDataset) -> float:
        return pr_auc(val.labels, self.predict_proba(val))
