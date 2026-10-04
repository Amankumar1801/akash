# Phase 3: classifier system, validated on SYNTHETIC data

**Read this first.** Every number below comes from a synthetic TCE set (planets, eclipsing
binaries, "systematic" periodic dips with varying depth, and selection-biased noise TCEs, built
with the Phase 2 pipeline). It shows the training/evaluation/uncertainty/registry machinery
behaves correctly. **It says nothing about performance on real Kepler or TESS data**, which needs
the real DR25 training set (`scripts/build_kepler_training_set.py`) and is the actual Phase 3
science result still to be produced on a machine with internet.

Reproduce: `uv run python scripts/train_transit.py --synthetic 320 --name transit-synthetic`
(~2 min, 1 CPU). Split: star-grouped hash split; rows train/val/calib/test = 307/49/34/41, so
**the test set has 41 rows (19 positives)**; all CIs are wide.

## Result (test split, star-grouped bootstrap 95% CI)
| Model | PR-AUC | ROC-AUC | Brier | ECE |
|---|---|---|---|---|
| SNR-only baseline | 0.43 (0.28-0.66) | 0.47 | 0.251 | 0.143 |
| LightGBM | 0.90 (0.76-0.995) | 0.91 | 0.106 | 0.101 |
| 1D CNN, 5-seed ensemble | 0.84 (0.66-0.96) | 0.88 | 0.139 | 0.117 |
| Council, calibrated | 0.90 (0.74-1.00) | 0.93 | 0.101 | 0.130 |

Decision threshold 0.445 (chosen on validation, frozen): precision 0.85, recall 0.90, FPR 0.14.
The classifier clearly beats the SNR baseline (by design the synthetic classes overlap in SNR);
the council is **not** distinguishable from LightGBM alone here (overlapping CIs).

## Findings worth keeping
- **The CNN is the weaker family on small data** (0.84 vs 0.90, CIs overlap). Expected with ~300
  training rows. Single-seed CNN test PR-AUC varied 0.75-0.89 across seeds (spread ~0.14), which
  is the argument for the ensemble.
- **A real bug was found by measuring:** checkpointing the CNN on validation PR-AUC restored an
  early epoch (train PR-AUC 0.57 < val 0.80). Switching to validation log-loss and a smaller batch
  / higher learning rate raised held-out PR-AUC from ~0.65 to 0.75-0.89 (ADR 0004 #7).
- **Conformal coverage is valid, and single splits are noisy.** Over 40 independent re-splits
  (GBM + Platt + conformal, alpha=0.1) mean coverage was 0.931 overall, 0.930 for class 0, 0.932
  for class 1 (target 0.90). Individual splits ranged 0.75-1.00 for class 0. One early split
  showed 0.74 and looked like a bug; it was noise. The re-split validity check is now a test.
- **Calibration showed no ECE benefit here:** mean ECE 0.130 -> 0.128 over the same 40 re-splits
  (Brier not degraded). With 34-57 calibration rows and ~40 test rows, 10-bin ECE is
  noise-dominated. On a deliberately overconfident synthetic score with 4000 rows, Platt and
  isotonic cut ECE by >50% (unit-tested), so the code works; whether it helps on real data is open.
- With a 34-row calibration set, conformal sets are conservative (46% "uncertain").
- Council cross-family disagreement flagged 24% of test rows; whether disagreement predicts errors
  is untested.

## Still to do on real data (the actual Phase 3 acceptance)
1. Build the Kepler DR25 training set; confirm the TCE-table column names match your download.
2. Train, report PR-AUC with CIs vs the SNR baseline, calibration (ECE/reliability), conformal
   coverage, recall by SNR/period/depth, and the error analysis (are the top false positives
   eclipsing binaries?).
3. Kepler -> TESS domain-shift study: score TOIs with the Kepler model, report degradation and
   whether the OOD flag fires.
4. Verify the frozen split manifest is committed and its digest checked in CI.
