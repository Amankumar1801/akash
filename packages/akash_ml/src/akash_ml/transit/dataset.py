"""TransitDataset: arrays for one set of TCEs + content hash + npz persistence."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from akash_core.ids import sha256_bytes
from akash_science.lightcurve.types import F64

from .features import FEATURE_NAMES, FEATURE_VERSION

GLOBAL_LEN, LOCAL_LEN = 2001, 201


@dataclass
class TransitDataset:
    tce_ids: np.ndarray  # str
    star_ids: np.ndarray  # int64 (grouping key for splits)
    labels: np.ndarray  # int8: 1 = planet candidate, 0 = false positive
    global_views: np.ndarray  # float32 (N, 2001)
    local_views: np.ndarray  # float32 (N, 201)
    features: np.ndarray  # float64 (N, F), NaN allowed
    meta: dict[str, np.ndarray] = field(default_factory=dict)  # snr, period_d, depth_ppm, ...
    feature_version: str = FEATURE_VERSION

    def __post_init__(self) -> None:
        n = len(self.labels)
        ok = (len(self.tce_ids) == n == len(self.star_ids) == len(self.global_views)
              == len(self.local_views) == len(self.features))
        if not ok:
            raise ValueError("TransitDataset arrays have inconsistent lengths")
        if self.features.shape[1] != len(FEATURE_NAMES):
            raise ValueError("feature width does not match FEATURE_NAMES")
        if self.global_views.shape[1] != GLOBAL_LEN or self.local_views.shape[1] != LOCAL_LEN:
            raise ValueError("unexpected view lengths")

    def __len__(self) -> int:
        return len(self.labels)

    def subset(self, idx: np.ndarray) -> TransitDataset:
        return TransitDataset(
            self.tce_ids[idx], self.star_ids[idx], self.labels[idx], self.global_views[idx],
            self.local_views[idx], self.features[idx], {k: v[idx] for k, v in self.meta.items()},
            self.feature_version)

    @staticmethod
    def concat(parts: list[TransitDataset]) -> TransitDataset:
        meta_keys = parts[0].meta.keys()
        return TransitDataset(
            np.concatenate([p.tce_ids for p in parts]), np.concatenate([p.star_ids for p in parts]),
            np.concatenate([p.labels for p in parts]),
            np.concatenate([p.global_views for p in parts]),
            np.concatenate([p.local_views for p in parts]),
            np.concatenate([p.features for p in parts]),
            {k: np.concatenate([p.meta[k] for p in parts]) for k in meta_keys},
            parts[0].feature_version)

    def _arrays(self) -> dict[str, np.ndarray]:
        d = {"tce_ids": self.tce_ids.astype(str), "star_ids": self.star_ids,
             "labels": self.labels, "global_views": self.global_views,
             "local_views": self.local_views, "features": self.features,
             "feature_version": np.array(self.feature_version)}
        d.update({f"meta_{k}": v for k, v in self.meta.items()})
        return d

    def content_hash(self) -> str:
        h = []
        for k in sorted(self._arrays()):
            a = np.ascontiguousarray(self._arrays()[k])
            h.append(k + sha256_bytes(a.tobytes()))
        return sha256_bytes("|".join(h).encode())

    def save(self, path: str | Path) -> str:
        buf = io.BytesIO()
        arrays: dict[str, Any] = dict(self._arrays())
        np.savez_compressed(buf, **arrays)
        Path(path).write_bytes(buf.getvalue())
        return self.content_hash()

    @classmethod
    def load(cls, path: str | Path) -> TransitDataset:
        z = np.load(path, allow_pickle=False)  # never unpickle
        return cls(
            z["tce_ids"], z["star_ids"], z["labels"], z["global_views"], z["local_views"],
            z["features"], {k[5:]: z[k] for k in z.files if k.startswith("meta_")},
            str(z["feature_version"]))


def as_f64(x: np.ndarray) -> F64:
    return np.asarray(x, dtype=np.float64)
