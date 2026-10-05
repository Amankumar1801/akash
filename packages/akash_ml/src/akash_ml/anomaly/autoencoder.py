"""1D convolutional autoencoder on fixed-length binned light-curve representations.

Reconstruction error flags unusual MORPHOLOGY relative to the reference population; latent kNN
distance flags unusual position in the learned embedding. Inputs are clipped to +-CLIP robust
sigmas (a 100-sigma flare would otherwise dominate training). State is persisted as a plain
state_dict (loaded with weights_only=True)."""

from __future__ import annotations

import io

import numpy as np
import torch
from akash_science.lightcurve.types import F64
from akash_science.lightcurve.variability import REP_LEN
from torch import nn

CLIP = 20.0
LATENT = 8


class _AE(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.enc = nn.Sequential(
            nn.Conv1d(1, 8, 7, 2, 3), nn.ReLU(), nn.Conv1d(8, 16, 5, 2, 2), nn.ReLU(),
            nn.Conv1d(16, 32, 5, 2, 2), nn.ReLU(), nn.Flatten(),
            nn.Linear(32 * (REP_LEN // 8), LATENT))
        self.dec_fc = nn.Sequential(nn.Linear(LATENT, 32 * (REP_LEN // 8)), nn.ReLU())
        self.dec = nn.Sequential(
            nn.ConvTranspose1d(32, 16, 4, 2, 1), nn.ReLU(), nn.ConvTranspose1d(16, 8, 4, 2, 1),
            nn.ReLU(), nn.ConvTranspose1d(8, 1, 4, 2, 1))

    def encode(self, x: torch.Tensor) -> torch.Tensor:
        z: torch.Tensor = self.enc(x)
        return z

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.dec_fc(self.encode(x)).view(-1, 32, REP_LEN // 8)
        out: torch.Tensor = self.dec(h)
        return out


def _prep(reps: np.ndarray) -> torch.Tensor:
    return torch.from_numpy(np.clip(reps, -CLIP, CLIP).astype(np.float32))[:, None, :]


class Autoencoder:
    def __init__(self, seed: int = 0) -> None:
        self.seed = seed
        self.net: _AE | None = None

    def fit(self, fit_reps: np.ndarray, hold_reps: np.ndarray, epochs: int = 80,
            patience: int = 10, batch: int = 32, lr: float = 2e-3) -> Autoencoder:
        torch.manual_seed(self.seed)
        torch.set_num_threads(1)
        rng = np.random.default_rng(self.seed)
        self.net = _AE()
        x, xh = _prep(fit_reps), _prep(hold_reps)
        opt = torch.optim.Adam(self.net.parameters(), lr=lr)
        best, bad, state = float("inf"), 0, None
        for _ in range(epochs):
            self.net.train()
            perm = rng.permutation(len(x))
            for i in range(0, len(perm), batch):
                b = torch.from_numpy(perm[i:i + batch])
                opt.zero_grad()
                loss = ((self.net(x[b]) - x[b]) ** 2).mean()
                loss.backward()
                opt.step()
            self.net.eval()
            with torch.no_grad():
                v = float(((self.net(xh) - xh) ** 2).mean())
            if v < best - 1e-5:
                best, bad, state = v, 0, {k: t.clone() for k, t in self.net.state_dict().items()}
            else:
                bad += 1
                if bad >= patience:
                    break
        if state is not None:
            self.net.load_state_dict(state)
        self.net.eval()
        return self

    def _run(self, reps: np.ndarray) -> tuple[torch.Tensor, torch.Tensor]:
        assert self.net is not None, "autoencoder not fitted"
        x = _prep(reps)
        with torch.no_grad():
            return x, self.net(x)

    def recon_residual(self, reps: np.ndarray) -> F64:
        """Per-bin squared error, shape (N, REP_LEN): WHERE the shape is unusual."""
        x, y = self._run(reps)
        return np.asarray(((x - y) ** 2)[:, 0, :].numpy(), dtype=np.float64)

    def recon_error(self, reps: np.ndarray) -> F64:
        return np.asarray(self.recon_residual(reps).mean(axis=1), dtype=np.float64)

    def embed(self, reps: np.ndarray) -> F64:
        assert self.net is not None
        with torch.no_grad():
            return np.asarray(self.net.encode(_prep(reps)).numpy(), dtype=np.float64)

    def to_bytes(self) -> bytes:
        assert self.net is not None
        buf = io.BytesIO()
        torch.save(self.net.state_dict(), buf)
        return buf.getvalue()

    @classmethod
    def from_bytes(cls, data: bytes, seed: int = 0) -> Autoencoder:
        m = cls(seed)
        m.net = _AE()
        m.net.load_state_dict(torch.load(io.BytesIO(data), weights_only=True))
        m.net.eval()
        return m
