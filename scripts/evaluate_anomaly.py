"""Reproduce the Phase 4 synthetic evaluation end to end (about 3 minutes on one CPU).

Protocol (every choice that could leak is made before the test population is touched):
  reference  : N synthetic ordinary stars -> detectors fit on ~80% of stars, score distribution
               calibrated on the held-out ~20%
  validation : separate seeds; the detector-combination rule is chosen here by mean per-kind
               detection at 5% FPR
  test       : another set of seeds, evaluated once with the rule fixed
Use --test-seed to evaluate on a population nobody has looked at.

    uv run python scripts/evaluate_anomaly.py --test-seed 1700 --json evaluation/anomaly-synthetic.json
"""

from __future__ import annotations

import argparse
import json
import warnings

import numpy as np
from akash_ml.anomaly.engine import AnomalyEngine
from akash_ml.anomaly.evaluate import evaluate_recovery, rank_stability, select_aggregator
from akash_ml.anomaly.reference import ReferencePopulation
from akash_science.lightcurve.variability import extract_variability
from akash_science.synthetic_anomaly import make_population


def main() -> None:
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference-size", type=int, default=450)
    ap.add_argument("--n-normal-eval", type=int, default=60)
    ap.add_argument("--n-per-kind", type=int, default=15)
    ap.add_argument("--reference-seed", type=int, default=100)
    ap.add_argument("--validation-seed", type=int, default=300)
    ap.add_argument("--test-seed", type=int, required=True)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    kinds = {"normal": a.n_normal_eval, **{k: a.n_per_kind for k in (
        "dimming", "flares", "extreme_amp", "unusual_period", "eclipsing", "artifact_step",
        "artifact_flagged")}}
    rl, _ = make_population({"normal": a.reference_size}, a.reference_seed)
    vl, vlab = make_population(kinds, a.validation_seed)
    tl, tlab = make_population(kinds, a.test_seed)
    rv, vv, tv = ([extract_variability(x) for x in lcs] for lcs in (rl, vl, tl))

    refs = {s: ReferencePopulation("synthetic-normal-v1", {"kind": "synthetic ordinary stars"},
                                   seed=s).fit(rv, np.arange(len(rv))) for s in (0, 1)}
    best, val_scores = select_aggregator(refs[0], vv, vlab)
    print("validation mean TPR@5%FPR by rule:", {k: round(v, 3) for k, v in val_scores.items()},
          "-> chosen:", best)
    for r in refs.values():
        r.set_aggregate(best)
    res = {s: [AnomalyEngine(r).analyze_extracted(v) for v in tv] for s, r in refs.items()}
    m = evaluate_recovery(res[0], tlab)
    sev = lambda rs: np.array([r.severity if r.severity is not None else -1e9 for r in rs])  # noqa: E731
    m["stability_across_seeds"] = rank_stability(sev(res[0]), sev(res[1]))
    m["chosen_aggregate"], m["validation_scores"] = best, val_scores
    print(json.dumps({k: v for k, v in m.items() if k not in ("per_kind", "top_k")}, indent=1,
                     default=float))
    for k, v in m["per_kind"].items():
        print(f"  {k:16s} TPR@5%FPR={v['tpr_at_5pct_fpr']:.2f} artifact_flagged={v['artifact_flagged']:.2f}")
    for k, v in m["top_k"].items():
        print(f"  top {k}: artifact rate {v['artifact_rate_ungated']:.2f} -> gated "
              f"{v['artifact_rate_gated']:.2f}; precision {v['precision_interesting_gated']:.2f}")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(m, f, indent=1, default=float)


if __name__ == "__main__":
    main()
