"""Deep ensembles and the cross-family council. Disagreement is itself reported evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from akash_science.lightcurve.types import F64

from ..interfaces import TransitModel
from .dataset import TransitDataset

DISAGREE_RANGE = 0.3  # family-mean probabilities further apart than this => flag


class Ensemble:
    """Several seeds of ONE family (epistemic spread from initialisation/data order)."""

    def __init__(self, members: list[TransitModel], family: str) -> None:
        if not members:
            raise ValueError("empty ensemble")
        self.members, self.family = members, family
        self.version = f"{family}-ens{len(members)}"

    def member_probs(self, ds: TransitDataset) -> F64:
        return np.stack([m.predict_proba(ds) for m in self.members])

    def predict_proba(self, ds: TransitDataset) -> F64:
        return np.asarray(self.member_probs(ds).mean(axis=0), dtype=np.float64)

    def spread(self, ds: TransitDataset) -> F64:
        return np.asarray(self.member_probs(ds).std(axis=0), dtype=np.float64)


@dataclass
class CouncilOutput:
    prob: F64  # mean of family means (raw, pre-calibration)
    family_probs: dict[str, F64]
    range: F64  # max-min across family means
    disagree: np.ndarray  # bool


class Council:
    """Independent model FAMILIES (e.g. gbm vs cnn1d). Disagreement => manual review."""

    def __init__(self, families: Mapping[str, TransitModel]) -> None:
        if not families:
            raise ValueError("empty council")
        self.families = families

    def predict(self, ds: TransitDataset) -> CouncilOutput:
        fp = {k: m.predict_proba(ds) for k, m in self.families.items()}
        stack = np.stack(list(fp.values()))
        rng = stack.max(axis=0) - stack.min(axis=0)
        return CouncilOutput(stack.mean(axis=0), fp, rng, rng > DISAGREE_RANGE)
