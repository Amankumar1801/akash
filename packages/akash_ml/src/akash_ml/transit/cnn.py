"""Two-branch 1D CNN (AstroNet lineage): global view + local view + scalar MLP -> logit.

Small on purpose (~40k parameters): trains on CPU in minutes. Requires torch (optional extra).
Weights are saved as a plain state_dict and loaded with weights_only=True (no pickle execution).
"""

from __future__ import annotations

import io
from typing import Any

import numpy as np
import torch
from akash_science.lightcurve.types import F64
from torch import nn

from .dataset import GLOBAL_LEN, LOCAL_LEN, TransitDataset
from .features import CNN_SCALARS, FEATURE_NAMES

_COLS = [FEATURE_NAMES.index(n) for n in CNN_SCALARS]


def _branch(ch: tuple[int, ...]) -> nn.Sequential:
    layers: list[nn.Module] = []
    prev = 1
    for c in ch:
        layers += [nn.Conv1d(prev, c, 5, padding=2), nn.ReLU(),
                   nn.Conv1d(c, c, 5, padding=2), nn.ReLU(), nn.MaxPool1d(3, 2, padding=1)]
        prev = c
    layers += [nn.AdaptiveMaxPool1d(8), nn.Flatten()]
    return nn.Sequential(*layers)


class _Net(nn.Module):
    def __init__(self, n_scalar: int) -> None:
        super().__init__()
        self.g, self.loc = _branch((8, 16, 16)), _branch((8, 16))
        self.s = nn.Sequential(nn.Linear(n_scalar, 16), nn.ReLU())
        self.head = nn.Sequential(nn.Linear(16 * 8 + 16 * 8 + 16, 64), nn.ReLU(),
                                  nn.Dropout(0.2), nn.Linear(64, 1))

    def forward(self, g: torch.Tensor, loc: torch.Tensor, s: torch.Tensor) -> torch.Tensor:
        out: torch.Tensor = self.head(
            torch.cat([self.g(g), self.loc(loc), self.s(s)], dim=1)).squeeze(1)
        return out


def normalize_views(g: np.ndarray, loc: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """AstroNet convention per sample: subtract the median, then scale so the local-view minimum
    is -1. Amplitude is NOT lost: depth and SNR enter through the scalar branch."""
    g = g - np.median(g, axis=1, keepdims=True)
    loc = loc - np.median(loc, axis=1, keepdims=True)
    scale = np.maximum(-loc.min(axis=1, keepdims=True), 1e-6)
    return (g / scale).astype(np.float32), (loc / scale).astype(np.float32)


class CNNTransitModel:
    family = "cnn1d"

    def __init__(self, seed: int = 0, version: str = "cnn1d@1") -> None:
        self.seed, self.version = seed, version
        self.net: _Net | None = None
        self.mu = np.zeros(len(_COLS))
        self.sd = np.ones(len(_COLS))

    # -- inputs --
    def _scalars(self, ds: TransitDataset) -> np.ndarray:
        x = ds.features[:, _COLS].copy()
        bad = ~np.isfinite(x)
        x[bad] = np.broadcast_to(self.mu, x.shape)[bad]
        return ((x - self.mu) / self.sd).astype(np.float32)

    def _tensors(self, ds: TransitDataset) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        g, loc = normalize_views(ds.global_views, ds.local_views)
        return (torch.from_numpy(g)[:, None, :], torch.from_numpy(loc)[:, None, :],
                torch.from_numpy(self._scalars(ds)))

    # -- training --
    def fit(self, train: TransitDataset, val: TransitDataset, epochs: int = 40,
            patience: int = 10, batch: int = 16, lr: float = 3e-3) -> CNNTransitModel:
        torch.manual_seed(self.seed)
        torch.set_num_threads(1)
        rng = np.random.default_rng(self.seed)
        x = train.features[:, _COLS]
        self.mu, self.sd = np.nanmean(x, axis=0), np.nanstd(x, axis=0) + 1e-6
        self.net = _Net(len(_COLS))
        gt, lt, st = self._tensors(train)
        y = torch.from_numpy(train.labels.astype(np.float32))
        pos = float(y.sum())
        loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor((len(y) - pos) / max(pos, 1.0)))
        opt = torch.optim.AdamW(self.net.parameters(), lr=lr, weight_decay=1e-4)
        best, best_state, bad = float("inf"), None, 0
        yv = np.clip(val.labels.astype(np.float64), 0, 1)
        for _ in range(epochs):
            self.net.train()
            perm = rng.permutation(len(y))
            for i in range(0, len(perm), batch):
                b = torch.from_numpy(perm[i:i + batch])
                g, loc = gt[b], lt[b]
                if rng.random() < 0.5:  # phase-flip augmentation: transits are time-symmetric
                    g, loc = g.flip(-1), loc.flip(-1)
                opt.zero_grad()
                loss_fn(self.net(g, loc, st[b]), y[b]).backward()
                opt.step()
            # checkpoint on validation LOG-LOSS: smooth, unlike PR-AUC which on a few dozen rows
            # jumps around and latches onto an early lucky epoch (found empirically)
            pv = np.clip(self.predict_proba(val), 1e-6, 1 - 1e-6)
            score = float(-np.mean(yv * np.log(pv) + (1 - yv) * np.log(1 - pv)))
            if score < best - 1e-4:
                best, bad = score, 0
                best_state = {k: v.clone() for k, v in self.net.state_dict().items()}
            else:
                bad += 1
                if bad >= patience:
                    break
        if best_state is not None:
            self.net.load_state_dict(best_state)
        return self

    def predict_proba(self, ds: TransitDataset) -> F64:
        assert self.net is not None, "model not fitted"
        self.net.eval()
        g, loc, s = self._tensors(ds)
        with torch.no_grad():
            p = torch.sigmoid(self.net(g, loc, s)).numpy()
        return np.asarray(p, dtype=np.float64)

    def predict_from_views(self, g: np.ndarray, loc: np.ndarray, scalars: np.ndarray) -> float:
        """Single-sample prediction with custom views (used by occlusion explanations)."""
        assert self.net is not None
        gn, ln = normalize_views(g[None, :], loc[None, :])
        sc = ((np.where(np.isfinite(scalars), scalars, self.mu) - self.mu) / self.sd)
        self.net.eval()
        with torch.no_grad():
            p = torch.sigmoid(self.net(torch.from_numpy(gn)[:, None, :],
                                       torch.from_numpy(ln)[:, None, :],
                                       torch.from_numpy(sc[None, :].astype(np.float32))))
        return float(p.item())

    # -- persistence (state_dict only; loaded with weights_only=True) --
    def to_bytes(self) -> bytes:
        assert self.net is not None
        buf = io.BytesIO()
        torch.save(self.net.state_dict(), buf)
        return buf.getvalue()

    def meta(self) -> dict[str, Any]:
        return {"mu": self.mu.tolist(), "sd": self.sd.tolist(), "seed": self.seed,
                "version": self.version, "global_len": GLOBAL_LEN, "local_len": LOCAL_LEN}

    @classmethod
    def from_bytes(cls, data: bytes, meta: dict[str, Any]) -> CNNTransitModel:
        m = cls(meta["seed"], meta["version"])
        m.mu, m.sd = np.array(meta["mu"]), np.array(meta["sd"])
        m.net = _Net(len(_COLS))
        m.net.load_state_dict(torch.load(io.BytesIO(data), weights_only=True))
        return m
