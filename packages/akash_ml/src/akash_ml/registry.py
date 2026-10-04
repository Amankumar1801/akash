"""File-based model registry: one immutable directory per version, with everything needed to
reproduce and audit a prediction (feature version, data hash, split digest, code version).
MLflow logging can be layered on top; the registry itself has no external dependency."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from akash_core.errors import ValidationFailure

from .training import TrainedSystem, calibrator_from_dict
from .transit.ensemble import Council, Ensemble
from .transit.features import FEATURE_NAMES, FEATURE_VERSION
from .transit.gbm import GBMTransitModel
from .uncertainty.conformal import SplitConformal
from .uncertainty.ood import MahalanobisOOD


def save_system(root: str | Path, name: str, version: str, sysm: TrainedSystem) -> Path:
    d = Path(root) / name / version
    if d.exists():
        raise ValidationFailure(f"{d} already exists: registry versions are immutable")
    d.mkdir(parents=True)
    gbms = [m for m in sysm.members if m.family == "gbm"]
    cnns = [m for m in sysm.members if m.family == "cnn1d"]
    for i, g in enumerate(gbms):
        (d / f"gbm_{i}.txt").write_text(g.to_string())
    for i, c in enumerate(cnns):
        (d / f"cnn_{i}.pt").write_bytes(c.to_bytes())
        (d / f"cnn_{i}.json").write_text(json.dumps(c.meta()))
    (d / "calibrator.json").write_text(json.dumps(sysm.calibrator.to_dict()))
    (d / "conformal.json").write_text(json.dumps(
        {"alpha": sysm.conformal.alpha, "cc": sysm.conformal.class_conditional,
         "qhat": {str(k): v for k, v in sysm.conformal.qhat.items()}}))
    (d / "ood.json").write_text(json.dumps(sysm.ood.to_dict()))
    meta = {**sysm.meta, "name": name, "version": version, "n_gbm": len(gbms), "n_cnn": len(cnns),
            "threshold": sysm.threshold, "created_at": datetime.now(UTC).isoformat()}
    (d / "metadata.json").write_text(json.dumps(meta, indent=1, default=float))
    return d


def load_system(path: str | Path) -> TrainedSystem:
    from .transit.baseline import SnrBaseline
    d = Path(path)
    meta = json.loads((d / "metadata.json").read_text())
    if meta["feature_version"] != FEATURE_VERSION or meta["feature_names"] != list(FEATURE_NAMES):
        raise ValidationFailure("model was trained with a different feature set; refusing to load")
    gbms = [GBMTransitModel.from_string((d / f"gbm_{i}.txt").read_text(),
                                        f"gbm@1.s{meta['config']['seed'] + i}")
            for i in range(meta["n_gbm"])]
    families = {"gbm": Ensemble(gbms, "gbm")}  # type: ignore[arg-type]
    members: list[Any] = list(gbms)
    if meta["n_cnn"]:
        from .transit.cnn import CNNTransitModel
        cnns = [CNNTransitModel.from_bytes((d / f"cnn_{i}.pt").read_bytes(),
                                           json.loads((d / f"cnn_{i}.json").read_text()))
                for i in range(meta["n_cnn"])]
        families["cnn1d"] = Ensemble(cnns, "cnn1d")  # type: ignore[arg-type]
        members += cnns
    cj = json.loads((d / "conformal.json").read_text())
    conf = SplitConformal(cj["alpha"], cj["cc"])
    conf.qhat = {int(k): v for k, v in cj["qhat"].items()}
    return TrainedSystem(
        SnrBaseline(), Council(families), members,
        calibrator_from_dict(json.loads((d / "calibrator.json").read_text())), conf,
        MahalanobisOOD.from_dict(json.loads((d / "ood.json").read_text())),
        meta["threshold"], meta)
