"""Injection-recovery sensitivity experiment on SYNTHETIC light curves (see synthetic.py caveat).

    uv run python scripts/injection_recovery.py --trials 200 --controls 40 --seed 7
"""

from __future__ import annotations

import argparse
import json
import warnings

import numpy as np
from akash_science.injection.experiment import run_controls, run_trials, summarize_by_snr
from akash_science.lightcurve.pipeline import LightCurvePipeline
from akash_science.synthetic import make_synthetic_lc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=100)
    ap.add_argument("--controls", type=int, default=30)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--json", type=str, default="")
    a = ap.parse_args()
    warnings.filterwarnings("ignore")
    pipe = LightCurvePipeline()
    mk = lambda rng: make_synthetic_lc(rng)  # noqa: E731
    trials = run_trials(mk, pipe, a.trials, a.seed, depth_range=(1.5e-4, 3e-3))
    edges = [0, 3, 5, 7, 9, 12, 16, 25, 1e9]
    rows = summarize_by_snr(trials, edges)
    print(f"{'SNR bin':>12} {'n':>4} {'recovered':>9} {'frac':>6} {'alias':>6}")
    for r in rows:
        hi = "inf" if r["snr_hi"] > 1e8 else f"{r['snr_hi']:.0f}"
        print(f"{r['snr_lo']:>6.0f}-{hi:>5} {int(r['n']):>4} {int(r['recovered']):>9} "
              f"{r['recovery_frac']:>6.2f} {r['alias_frac']:>6.2f}")
    hits, n = run_controls(mk, pipe, a.controls, a.seed + 1)
    print(f"controls: {hits}/{n} produced a TCE (pipeline false-alarm rate on synthetic noise)")
    rec = [t for t in trials if t.recovered and t.found_period]
    errs = np.array([abs(t.found_period - t.spec.period_d) / t.spec.period_d for t in rec])  # type: ignore[operator]
    if len(errs):
        print(f"period error (recovered): median {np.median(errs):.2e}, 95th pct {np.percentile(errs,95):.2e}")
    if a.json:
        json.dump({"rows": rows, "controls": [hits, n], "seed": a.seed}, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
