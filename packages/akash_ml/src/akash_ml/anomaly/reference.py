"""Reference population + calibrated detector ensemble.

"Anomalous" is only meaningful relative to a population, so every score carries the reference
id. Detectors are fit on ~80% of reference STARS; the score distribution used to convert raw
scores to percentiles is measured on the other ~20% (held out), because scoring the stars a
detector was trained on makes the reference look artificially normal.

Detectors (scores oriented so higher = more unusual; combined by averaging percentile RANKS,
never raw scores, which have incompatible scales):
  iforest     Isolation Forest on robust-scaled features
  lof         Local Outlier Factor (novelty mode) on the same features
  ae_recon    autoencoder reconstruction error (unusual shape)
  latent_knn  mean distance to k nearest reference embeddings (unusual in latent space)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
from akash_science.lightcurve.types import F64
from akash_science.lightcurve.variability import (
    DEFAULT_ARTIFACT_THRESHOLDS,
    FEATURE_NAMES,
    VARIABILITY_VERSION,
    VariabilityResult,
)
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor, NearestNeighbors

if TYPE_CHECKING:  # torch is optional: the autoencoder is imported only when one is used
    from .autoencoder import Autoencoder


def _autoencoder_cls() -> type[Autoencoder]:
    try:
        from .autoencoder import Autoencoder as cls
    except ModuleNotFoundError as e:
        if e.name != "torch":
            raise
        raise RuntimeError("This anomaly reference uses the autoencoder, which needs PyTorch. "
                           "Install it with: uv sync --all-packages --extra torch") from e
    return cls


DETECTORS = ("iforest", "lof", "ae_recon", "latent_knn")
CALIB_FRACTION = 0.2
K_LATENT = 10


def _holdout(star_id: int, salt: str) -> bool:
    h = hashlib.sha256(f"{salt}:{int(star_id)}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64 < CALIB_FRACTION


def aggregate_scores(m: F64, mode: str) -> F64:
    """Combine a (n_detectors, N) matrix. `mean` assumes detectors broadly agree; `top2`/`max`
    suit anomaly types that only some detectors can see (e.g. amplitude is invisible to the
    amplitude-normalised autoencoder). Percentile calibration against the held-out reference
    keeps the final score comparable whichever rule is used."""
    if mode == "mean":
        return np.asarray(m.mean(axis=0), dtype=np.float64)
    if mode == "max":
        return np.asarray(m.max(axis=0), dtype=np.float64)
    if mode == "top2":
        return np.asarray(np.sort(m, axis=0)[-2:].mean(axis=0), dtype=np.float64)
    raise ValueError(f"unknown aggregate {mode!r}")


def _pct(sorted_ref: F64, x: F64) -> F64:
    return np.asarray(np.searchsorted(sorted_ref, x, side="right") / len(sorted_ref) * 100.0,
                      dtype=np.float64)


@dataclass
class RefScores:
    raw: dict[str, F64]
    percentiles: dict[str, F64]
    aggregate: F64  # mean of detector percentiles (rank average)
    percentile: F64  # percentile of `aggregate` within the held-out reference
    severity: F64  # continuous, unbounded: how far into the tail (1.0 ~ the reference's p95)


@dataclass
class ReferencePopulation:
    ref_id: str
    criteria: dict[str, Any]
    seed: int = 0
    use_ae: bool = True
    aggregate: str = "top2"  # detector combination: mean | top2 | max (chosen on validation)
    features: F64 = field(default_factory=lambda: np.zeros((0, len(FEATURE_NAMES))))
    reps: F64 = field(default_factory=lambda: np.zeros((0, 1)))
    star_ids: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    artifact_metrics: dict[str, F64] = field(default_factory=dict)
    median: F64 = field(default_factory=lambda: np.zeros(0))
    scale: F64 = field(default_factory=lambda: np.ones(0))  # IQR-based, for the detectors
    mad: F64 = field(default_factory=lambda: np.ones(0))  # for driver z-scores
    artifact_thresholds: dict[str, float] = field(default_factory=dict)
    calib_sorted: dict[str, F64] = field(default_factory=dict)
    agg_sorted: F64 = field(default_factory=lambda: np.zeros(0))
    version: str = VARIABILITY_VERSION
    _iso: IsolationForest | None = None
    _lof: LocalOutlierFactor | None = None
    _ae: Autoencoder | None = None
    _knn: NearestNeighbors | None = None
    _hold_pcts: F64 = field(default_factory=lambda: np.zeros((0, 0)))

    # ---------- fitting ----------
    def fit(self, vrs: list[VariabilityResult], star_ids: np.ndarray) -> ReferencePopulation:
        self.features = np.stack([v.features for v in vrs])
        self.reps = np.stack([v.representation for v in vrs]).astype(np.float32)
        self.star_ids = np.asarray(star_ids, dtype=np.int64)
        self.artifact_metrics = {k: np.array([v.artifact[k] for v in vrs])
                                 for k in vrs[0].artifact}
        self._fit_models()
        return self

    def _scale(self, x: F64) -> F64:
        return np.asarray((x - self.median) / self.scale, dtype=np.float64)

    def _fit_models(self, pretrained_ae: Autoencoder | None = None) -> None:
        hold = np.array([_holdout(s, f"{self.ref_id}:{self.seed}") for s in self.star_ids])
        if hold.sum() < 10 or (~hold).sum() < 30:
            raise ValueError("reference population too small: need >=30 fit and >=10 held-out rows")
        q1, q3 = np.percentile(self.features, [25, 75], axis=0)
        self.median = np.median(self.features, axis=0)
        self.scale = np.where(q3 - q1 > 1e-9, q3 - q1, 1.0)
        # z-score scale: MAD; for zero-inflated features (dip/flare counts) MAD is 0, so fall back
        # to the std, otherwise those features are floored at scale 1 and out-voted by amplitude
        mad = 1.4826 * np.median(np.abs(self.features - self.median), axis=0)
        std = self.features.std(axis=0)
        self.mad = np.where(mad > 1e-9, mad, np.where(std > 1e-9, std, 1.0))
        fit_x = self._scale(self.features[~hold])
        self._iso = IsolationForest(n_estimators=300, random_state=self.seed).fit(fit_x)
        self._lof = LocalOutlierFactor(n_neighbors=20, novelty=True).fit(fit_x)
        if self.use_ae:
            self._ae = pretrained_ae or _autoencoder_cls()(self.seed).fit(self.reps[~hold],
                                                                   self.reps[hold])
            self._knn = NearestNeighbors(n_neighbors=K_LATENT).fit(self._ae.embed(self.reps[~hold]))
        raw = self._raw(self.features[hold], self.reps[hold])
        self.calib_sorted = {k: np.sort(v) for k, v in raw.items()}
        self._hold_pcts = np.stack([_pct(self.calib_sorted[k], raw[k]) for k in raw])
        self.set_aggregate(self.aggregate)
        # artifact thresholds adapt to the reference: p99.5 of each ratio, never below 2.0
        self.artifact_thresholds = {
            k: float(max(2.0, np.percentile(self.artifact_metrics[k], 99.5)))
            for k in ("step_ratio", "ramp_ratio")}
        for k in ("flagged_fraction", "outlier_flag_overlap"):  # absolute, not reference-derived
            self.artifact_thresholds[k] = DEFAULT_ARTIFACT_THRESHOLDS[k]

    def set_aggregate(self, mode: str) -> None:
        """Switch the detector-combination rule without refitting any model."""
        self.aggregate = mode
        self.agg_sorted = np.sort(aggregate_scores(self._hold_pcts, mode))

    # ---------- scoring ----------
    def _raw(self, features: F64, reps: np.ndarray) -> dict[str, F64]:
        assert self._iso is not None and self._lof is not None
        x = self._scale(features)
        out = {"iforest": -self._iso.score_samples(x), "lof": -self._lof.score_samples(x)}
        if self.use_ae:
            assert self._ae is not None and self._knn is not None
            out["ae_recon"] = self._ae.recon_error(reps)
            out["latent_knn"] = self._knn.kneighbors(self._ae.embed(reps))[0].mean(axis=1)
        return {k: np.asarray(v, dtype=np.float64) for k, v in out.items()}

    def score(self, features: F64, reps: np.ndarray) -> RefScores:
        features = np.atleast_2d(features)
        reps = np.atleast_2d(reps)
        raw = self._raw(features, reps)
        pcts = {k: _pct(self.calib_sorted[k], v) for k, v in raw.items()}
        agg = aggregate_scores(np.stack(list(pcts.values())), self.aggregate)
        sev = []
        for k, v in raw.items():
            p50, p95 = np.percentile(self.calib_sorted[k], [50, 95])
            sev.append((v - p50) / max(p95 - p50, 1e-9))
        return RefScores(raw, pcts, agg, _pct(self.agg_sorted, agg),
                         aggregate_scores(np.stack(sev), self.aggregate))

    def driver_z(self, features: F64) -> F64:
        """Robust z of each feature vs the reference (signed): which features are unusual."""
        return np.asarray((features - self.median) / self.mad, dtype=np.float64)

    def localize(self, reps: np.ndarray) -> F64:
        """Per-bin reconstruction error (where in the baseline the shape is unusual)."""
        assert self._ae is not None, "reference was built without an autoencoder"
        return self._ae.recon_residual(np.atleast_2d(reps))

    # ---------- persistence: refit deterministically from stored data; never unpickle ----------
    def fingerprint(self) -> str:
        return hashlib.sha256(np.round(self.agg_sorted, 9).tobytes()).hexdigest()

    def meta(self) -> dict[str, Any]:
        return {"ref_id": self.ref_id, "criteria": self.criteria, "seed": self.seed,
                "use_ae": self.use_ae, "aggregate": self.aggregate, "version": self.version,
                "n": len(self.features),
                "feature_names": list(FEATURE_NAMES), "fingerprint": self.fingerprint(),
                "artifact_thresholds": self.artifact_thresholds}

    def save(self, directory: str) -> None:
        from pathlib import Path
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=False)
        arrays: dict[str, Any] = {"features": self.features, "reps": self.reps,
                                  "star_ids": self.star_ids}
        arrays.update({f"art_{k}": v for k, v in self.artifact_metrics.items()})
        np.savez_compressed(d / "reference.npz", **arrays)
        if self._ae is not None:
            (d / "autoencoder.pt").write_bytes(self._ae.to_bytes())
        (d / "meta.json").write_text(json.dumps(self.meta(), indent=1))

    @classmethod
    def load(cls, directory: str) -> ReferencePopulation:
        from pathlib import Path
        d = Path(directory)
        meta = json.loads((d / "meta.json").read_text())
        if meta["feature_names"] != list(FEATURE_NAMES) or meta["version"] != VARIABILITY_VERSION:
            raise ValueError("reference was built with a different feature set")
        z = np.load(d / "reference.npz", allow_pickle=False)
        ref = cls(meta["ref_id"], meta["criteria"], meta["seed"], meta["use_ae"], meta["aggregate"])
        ref.features, ref.reps, ref.star_ids = z["features"], z["reps"], z["star_ids"]
        ref.artifact_metrics = {k[4:]: z[k] for k in z.files if k.startswith("art_")}
        ae = (_autoencoder_cls().from_bytes((d / "autoencoder.pt").read_bytes(), meta["seed"])
              if meta["use_ae"] else None)
        ref._fit_models(pretrained_ae=ae)  # IF/LOF/kNN refit deterministically; AE reused
        if ref.fingerprint() != meta["fingerprint"]:
            raise ValueError("reference refit does not reproduce the saved score distribution")
        return ref
