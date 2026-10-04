"""Train, calibrate, and honestly evaluate the transit classifier system.

Protocol (every choice that could leak test information is fixed BEFORE test is touched):
  train      -> fit baseline, GBM, CNN seeds
  val        -> early stopping + the decision threshold (max F1, on calibrated council score)
  calib      -> probability calibrator + conformal quantiles (never train/val/test)
  test       -> evaluated once, with star-grouped bootstrap CIs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from akash_core.schemas import OODInfo, Prediction
from akash_core.schemas.assessment import Disagreement
from akash_science.lightcurve.types import F64

from . import metrics as M
from .transit.baseline import SnrBaseline
from .transit.dataset import TransitDataset
from .transit.ensemble import Council, Ensemble
from .transit.features import FEATURE_NAMES, FEATURE_VERSION, STELLAR_FEATURES
from .transit.gbm import GBMTransitModel
from .transit.splits import SplitManifest, assert_no_leakage
from .uncertainty.calibration import (
    IsotonicCalibrator,
    PlattCalibrator,
    calibrator_from_dict,
    fit_calibrator,
)
from .uncertainty.conformal import SplitConformal, class_coverage, coverage, set_label
from .uncertainty.ood import MahalanobisOOD

Z90 = 1.645
OOD_COLUMNS = [i for i, n in enumerate(FEATURE_NAMES) if n not in STELLAR_FEATURES]


@dataclass
class TrainConfig:
    n_cnn: int = 5
    cnn_epochs: int = 40
    n_gbm: int = 1
    run_cnn: bool = True
    conformal_alpha: float = 0.1
    bootstrap: int = 300
    seed: int = 0


@dataclass
class Scored:
    raw: F64
    prob: F64  # calibrated
    lo90: F64
    hi90: F64
    family_probs: dict[str, F64]
    disagree: np.ndarray
    ood_percentile: F64
    ood_flag: np.ndarray
    sets: np.ndarray
    set_labels: list[str]


@dataclass
class TrainedSystem:
    baseline: SnrBaseline
    council: Council
    members: list[Any]  # every individual model, for spread
    calibrator: PlattCalibrator | IsotonicCalibrator
    conformal: SplitConformal
    ood: MahalanobisOOD
    threshold: float
    meta: dict[str, Any] = field(default_factory=dict)

    def score(self, ds: TransitDataset) -> Scored:
        out = self.council.predict(ds)
        cal = self.calibrator.transform(out.prob)
        mem = np.stack([self.calibrator.transform(m.predict_proba(ds)) for m in self.members])
        sd = mem.std(axis=0)
        sets = self.conformal.predict_sets(cal)
        pct = self.ood.percentile(ds.features)
        lo, hi = np.clip(cal - Z90 * sd, 0, cal), np.clip(cal + Z90 * sd, cal, 1)
        return Scored(out.prob, cal, lo, hi,
                      out.family_probs, out.disagree, pct, self.ood.flag(ds.features), sets,
                      [set_label(r) for r in sets])

    def to_prediction(self, s: Scored, i: int) -> tuple[Prediction, OODInfo]:
        """Bridge to the core Assessment schema. interval_90 is ENSEMBLE SPREAD (model
        uncertainty), not a confidence interval for the label; conformal sets are the
        coverage-guaranteed statement."""
        pred = Prediction(
            planet_like_probability=float(s.prob[i]),
            interval_90=(float(s.lo90[i]), float(s.hi90[i])), calibrated=True,
            calibration_method=self.calibrator.method,
            model_versions=[m.version for m in self.members],
            disagreement=Disagreement(flag=bool(s.disagree[i]),
                                      range=float(self._range(s, i))))
        ood = OODInfo(flag=bool(s.ood_flag[i]), distance_percentile=float(s.ood_percentile[i]))
        return pred, ood

    @staticmethod
    def _range(s: Scored, i: int) -> float:
        v = [float(p[i]) for p in s.family_probs.values()]
        return min(max(v) - min(v), 1.0)


def _recall_bins(test: TransitDataset, p: F64, thr: float) -> dict[str, Any]:
    return {
        "snr": M.recall_by_bin(test.labels, p, thr, test.meta["snr"], [0, 7.1, 9, 12, 20, 1e9]),
        "period_d": M.recall_by_bin(test.labels, p, thr, test.meta["period_d"], [0, 2, 5, 10, 1e9]),
        "depth_ppm": M.recall_by_bin(test.labels, p, thr, test.meta["depth_ppm"],
                                     [0, 500, 1000, 3000, 1e12]),
    }


def _model_report(name: str, test: TransitDataset, p: F64, thr: float,
                  n_boot: int) -> dict[str, Any]:
    lo, hi = M.group_bootstrap_ci(M.pr_auc, test.labels, p, test.star_ids, n_boot)
    return {"name": name, "pr_auc": M.pr_auc(test.labels, p), "pr_auc_ci95": [lo, hi],
            "roc_auc": M.roc_auc(test.labels, p), "brier": M.brier(test.labels, p),
            "ece": M.ece(test.labels, p), "at_threshold": M.prf(test.labels, p, thr)}


def train_system(ds: TransitDataset, manifest: SplitManifest, cfg: TrainConfig,
                 code_version: str = "dev") -> TrainedSystem:
    idx = manifest.indices(ds.star_ids)
    assert_no_leakage(ds.star_ids, idx)  # hard stop: leakage invalidates everything downstream
    tr, va, ca, te = (ds.subset(idx[k]) for k in ("train", "val", "calib", "test"))

    baseline = SnrBaseline().fit(tr)
    gbms = [GBMTransitModel(seed=cfg.seed + i, version=f"gbm@1.s{cfg.seed + i}").fit(tr, va)
            for i in range(cfg.n_gbm)]
    families: dict[str, Any] = {"gbm": Ensemble(gbms, "gbm")}  # type: ignore[arg-type]
    members: list[Any] = list(gbms)
    if cfg.run_cnn:
        from .transit.cnn import CNNTransitModel  # torch is an optional extra
        cnns = [CNNTransitModel(cfg.seed + i, f"cnn1d@1.s{cfg.seed + i}")
                .fit(tr, va, epochs=cfg.cnn_epochs) for i in range(cfg.n_cnn)]
        families["cnn1d"] = Ensemble(cnns, "cnn1d")  # type: ignore[arg-type]
        members += cnns
    council = Council(families)

    cal_raw = council.predict(ca).prob
    calibrator = fit_calibrator(cal_raw, ca.labels)
    cal_cal = calibrator.transform(cal_raw)
    conformal = SplitConformal(cfg.conformal_alpha).fit(cal_cal, ca.labels)
    threshold = M.best_f1_threshold(va.labels, calibrator.transform(council.predict(va).prob))
    ood = MahalanobisOOD(OOD_COLUMNS).fit(tr.features)

    sysm = TrainedSystem(baseline, council, members, calibrator, conformal, ood, threshold)
    s = sysm.score(te)
    thr = threshold
    reports = {
        "baseline_snr": _model_report("baseline_snr", te, baseline.predict_proba(te), thr,
                                      cfg.bootstrap),
        "council_raw": _model_report("council_raw", te, s.raw, thr, cfg.bootstrap),
        "council_calibrated": _model_report("council_calibrated", te, s.prob, thr, cfg.bootstrap),
        **{f"family_{k}": _model_report(k, te, v, thr, cfg.bootstrap)
           for k, v in s.family_probs.items()},
    }
    err = np.argsort(-np.abs(s.prob - te.labels))[:10]
    cc = class_coverage(te.labels, s.sets)
    sysm.meta = {
        "feature_version": FEATURE_VERSION, "feature_names": list(FEATURE_NAMES),
        "code_version": code_version, "data_hash": ds.content_hash(),
        "split_manifest_digest": manifest.digest(), "config": cfg.__dict__,
        "n": {"train": len(tr), "val": len(va), "calib": len(ca), "test": len(te)},
        "n_pos_test": int(te.labels.sum()), "threshold": threshold,
        "calibration_method": calibrator.method,
        "metrics": {
            "models": reports,
            "reliability_calibrated": M.reliability_table(te.labels, s.prob),
            "recall_by_bin": _recall_bins(te, s.prob, thr),
            "conformal": {"alpha": cfg.conformal_alpha, "coverage": coverage(te.labels, s.sets),
                          "class_coverage": {str(k): v for k, v in cc.items()},
                          "frac_uncertain": float(np.mean(
                              [x == "uncertain" for x in s.set_labels])),
                          "frac_abstain": float(np.mean([x == "abstain" for x in s.set_labels]))},
            "ood": {"flag_rate_test": float(s.ood_flag.mean()),
                    "flag_rate_train": float(ood.flag(tr.features).mean())},
            "council_disagreement_rate": float(s.disagree.mean()),
            "worst_errors": [{"tce_id": str(te.tce_ids[i]), "label": int(te.labels[i]),
                              "prob": float(s.prob[i])} for i in err],
        },
    }
    return sysm


__all__ = ["TrainConfig", "TrainedSystem", "train_system", "calibrator_from_dict"]
