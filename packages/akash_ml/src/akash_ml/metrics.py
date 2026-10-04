from __future__ import annotations

from collections.abc import Callable

import numpy as np
from akash_science.lightcurve.types import F64
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score


def pr_auc(y: np.ndarray, p: F64) -> float:
    return float(average_precision_score(y, p)) if len(set(y.tolist())) == 2 else float("nan")


def roc_auc(y: np.ndarray, p: F64) -> float:
    return float(roc_auc_score(y, p)) if len(set(y.tolist())) == 2 else float("nan")


def brier(y: np.ndarray, p: F64) -> float:
    return float(brier_score_loss(y, np.clip(p, 0, 1)))


def prf(y: np.ndarray, p: F64, thr: float) -> dict[str, float]:
    pred = p >= thr
    tp, fp = int(((pred) & (y == 1)).sum()), int(((pred) & (y == 0)).sum())
    fn, tn = int(((~pred) & (y == 1)).sum()), int(((~pred) & (y == 0)).sum())
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * prec * rec / (prec + rec) if prec == prec and rec == rec and prec + rec > 0 else 0.0
    fpr = fp / (fp + tn) if fp + tn else float("nan")
    return {"threshold": thr, "precision": prec, "recall": rec, "f1": f1, "fpr": fpr,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def best_f1_threshold(y: np.ndarray, p: F64) -> float:
    """Choose on VALIDATION data only, then freeze for test."""
    cands = np.unique(np.round(p, 4))
    best, thr = -1.0, 0.5
    for c in cands:
        f1 = prf(y, p, float(c))["f1"]
        if f1 > best:
            best, thr = f1, float(c)
    return thr


def reliability_table(y: np.ndarray, p: F64, bins: int = 10) -> list[dict[str, float]]:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    out = []
    for b in range(bins):
        m = idx == b
        if m.any():
            out.append({"lo": float(edges[b]), "hi": float(edges[b + 1]), "n": int(m.sum()),
                        "mean_pred": float(p[m].mean()), "frac_pos": float(y[m].mean())})
    return out


def ece(y: np.ndarray, p: F64, bins: int = 10) -> float:
    n = len(y)
    return float(sum(r["n"] / n * abs(r["mean_pred"] - r["frac_pos"])
                     for r in reliability_table(y, p, bins))) if n else float("nan")


def recall_by_bin(y: np.ndarray, p: F64, thr: float, values: np.ndarray, edges: list[float]
                  ) -> list[dict[str, float]]:
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        m = (values >= lo) & (values < hi) & (y == 1)
        rows.append({"lo": lo, "hi": hi, "n_pos": int(m.sum()),
                     "recall": float((p[m] >= thr).mean()) if m.any() else float("nan")})
    return rows


def group_bootstrap_ci(metric: Callable[[np.ndarray, F64], float], y: np.ndarray, p: F64,
                       groups: np.ndarray, n_boot: int = 300, seed: int = 0,
                       level: float = 0.95) -> tuple[float, float]:
    """Percentile CI resampling STARS (not rows), so sibling TCEs stay together."""
    rng = np.random.default_rng(seed)
    uniq = np.unique(groups)
    by_group = {g: np.where(groups == g)[0] for g in uniq}
    vals = []
    for _ in range(n_boot):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([by_group[g] for g in pick])
        v = metric(y[idx], p[idx])
        if v == v:
            vals.append(v)
    if not vals:
        return float("nan"), float("nan")
    a = (1 - level) / 2
    return float(np.quantile(vals, a)), float(np.quantile(vals, 1 - a))
