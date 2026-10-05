"""Evaluation against injected, labelled anomalies. Reports what the engine can and cannot do,
including how much of the top of the ranking is instrumental junk with and without the gate."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from akash_science.synthetic_anomaly import ARTIFACTS, INTERESTING
from sklearn.metrics import roc_auc_score

from .engine import AnomalyResult, AnomalyStatus

DETECT_PCT = 95.0


EXPECTED_CATEGORY = {
    "dimming": "unusual_dips", "eclipsing": "unusual_dips", "flares": "flare_dominated",
    "extreme_amp": "high_amplitude_variability", "unusual_period": "unusual_periodicity"}


def _pct(r: AnomalyResult) -> float:
    return -1.0 if r.percentile is None else r.percentile


def _sev(r: AnomalyResult) -> float:
    return -1e9 if r.severity is None else r.severity


def tpr_at_fpr(sev: np.ndarray, pos: np.ndarray, neg: np.ndarray, fpr: float = 0.05) -> float:
    """Detection rate of `pos` at the severity threshold that lets `fpr` of `neg` through."""
    if not pos.any() or not neg.any():
        return math.nan
    thr = float(np.quantile(sev[neg], 1.0 - fpr))
    return float(np.mean(sev[pos] > thr))


def evaluate_recovery(results: list[AnomalyResult], labels: list[str],
                      top_fracs: tuple[float, ...] = (0.1, 0.2, 0.3)) -> dict[str, Any]:
    lab = np.array(labels)
    pct = np.array([_pct(r) for r in results])
    sev = np.array([_sev(r) for r in results])
    scored = np.array([r.status != AnomalyStatus.INSUFFICIENT_DATA for r in results])
    suspect = np.array([r.status == AnomalyStatus.ARTIFACT_SUSPECT for r in results])
    interesting = np.isin(lab, INTERESTING)
    artifact = np.isin(lab, ARTIFACTS)
    normal = lab == "normal"

    def auroc(pos: np.ndarray, neg: np.ndarray) -> float:
        m = (pos | neg) & scored
        return float(roc_auc_score(pos[m], sev[m])) if len(set(pos[m].tolist())) == 2 else math.nan

    def auroc_pct(pos: np.ndarray, neg: np.ndarray) -> float:
        m = (pos | neg) & scored
        return float(roc_auc_score(pos[m], pct[m])) if len(set(pos[m].tolist())) == 2 else math.nan

    per_kind = {}
    for k in sorted(set(labels)):
        m = lab == k
        per_kind[k] = {
            "n": int(m.sum()), "median_percentile": float(np.median(pct[m & scored]))
            if (m & scored).any() else math.nan,
            "detected_at_p95": float(np.mean((pct[m] >= DETECT_PCT) & ~suspect[m] & scored[m])),
            "tpr_at_5pct_fpr": tpr_at_fpr(sev, m & scored, normal & scored),
            "artifact_flagged": float(suspect[m].mean()),
            "not_scored": float((~scored[m]).mean())}

    cat_ok = {}
    for kind, want in EXPECTED_CATEGORY.items():
        sel = [r for r, lb in zip(results, labels, strict=True)
               if lb == kind and r.status == AnomalyStatus.SCORED]
        cat_ok[kind] = float(np.mean([r.category == want for r in sel])) if sel else math.nan

    order = np.argsort(-sev)  # rank by continuous severity (percentile saturates and ties)
    gated_order = [i for i in order if scored[i] and not suspect[i]]
    topk: dict[str, Any] = {}
    for frac in top_fracs:
        kk = max(int(math.ceil(frac * len(results))), 1)
        g = gated_order[:kk]
        topk[f"{frac:.0%}"] = {
            "k": kk, "artifact_rate_ungated": float(artifact[order[:kk]].mean()),
            "artifact_rate_gated": float(artifact[g].mean()) if g else math.nan,
            "precision_interesting_gated": float(interesting[g].mean()) if g else math.nan,
            "recall_interesting_gated":
                float(interesting[g].sum()) / max(int(interesting.sum()), 1)}
    return {
        "n": len(results), "auroc_interesting_vs_normal": auroc(interesting, normal),
        "auroc_interesting_vs_normal_percentile": auroc_pct(interesting, normal),
        "auroc_artifact_vs_normal": auroc(artifact, normal),
        "mean_tpr_at_5pct_fpr_interesting": float(np.nanmean(
            [per_kind[k]["tpr_at_5pct_fpr"] for k in INTERESTING if k in per_kind])),
        "min_tpr_at_5pct_fpr_interesting": float(np.nanmin(
            [per_kind[k]["tpr_at_5pct_fpr"] for k in INTERESTING if k in per_kind])),
        "per_kind": per_kind, "category_agreement": cat_ok, "top_k": topk,
        "false_artifact_flag_rate_interesting": float(suspect[interesting].mean()),
        "artifact_flag_rate_artifacts": float(suspect[artifact].mean()),
        "false_artifact_flag_rate_normal": float(suspect[normal].mean()),
    }


def rank_stability(pct_a: np.ndarray, pct_b: np.ndarray, top_frac: float = 0.1) -> dict[str, float]:
    """Pass continuous severity arrays (percentiles tie at the top and make Jaccard arbitrary)."""
    ra, rb = np.argsort(np.argsort(pct_a)), np.argsort(np.argsort(pct_b))
    rho = float(np.corrcoef(ra, rb)[0, 1])
    k = max(int(math.ceil(top_frac * len(pct_a))), 1)
    ta, tb = set(np.argsort(-pct_a)[:k].tolist()), set(np.argsort(-pct_b)[:k].tolist())
    return {"spearman": rho, "top_k_jaccard": len(ta & tb) / len(ta | tb), "k": float(k)}


def select_aggregator(
    ref: Any, vrs: list[Any], labels: list[str],
    modes: tuple[str, ...] = ("mean", "top2", "max"),
) -> tuple[str, dict[str, float]]:
    """Pick the detector-combination rule on a VALIDATION population, by mean per-kind detection at
    5% FPR. Pooled AUROC is deliberately not used: it ties when a rule is blind to a whole
    anomaly type (e.g. `mean` dilutes the amplitude signal the autoencoder cannot see), while
    per-kind detection exposes exactly that. Restores the reference's original rule on exit."""
    from .engine import AnomalyEngine
    original = ref.aggregate
    scores: dict[str, float] = {}
    try:
        for mode in modes:
            ref.set_aggregate(mode)
            res = [AnomalyEngine(ref).analyze_extracted(v) for v in vrs]
            scores[mode] = evaluate_recovery(res, labels)["mean_tpr_at_5pct_fpr_interesting"]
    finally:
        ref.set_aggregate(original)
    best = max(scores, key=lambda m: (scores[m], -modes.index(m)))  # ties -> simplest rule
    return best, scores
