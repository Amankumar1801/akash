# ADR 0004: Transit classifier system (Phase 3)
- Status: accepted

## Decisions
1. **Detection and classification stay separate.** BLS/TLS finds TCEs (Phase 2); this phase scores
   whether a TCE looks planet-like. The score is a triage signal, never a planet claim.
2. **Train from catalog ephemerides, not by re-searching.** Training views are folded at the
   catalog period/epoch/duration (`process_ephemeris`), as AstroNet did. The same function scores
   candidates whose ephemeris comes from elsewhere. Inference on BLS-found TCEs reuses it.
3. **Two model families behind one interface**: LightGBM on scalar features (SHAP-native, CPU,
   the strong baseline) and a small two-branch 1D CNN (global + local view + scalar MLP). A
   `Council` combines *families*; an `Ensemble` combines *seeds*. Cross-family disagreement
   (>0.3 apart) is reported, not hidden. No transformer: data volume does not justify it.
4. **Star-grouped, hash-based, frozen splits** (train/val/calib/test = 70/10/10/10). A star's
   split depends only on (salt, star_id), so rows can be added without reshuffling the test set;
   the manifest carries a digest and training aborts on any leakage or unknown star.
5. **Single-use roles for each split.** val: early stopping + decision threshold. calib:
   probability calibrator + conformal quantiles. test: evaluated once, with star-grouped
   bootstrap CIs. Nothing is tuned on test.
6. **Uncertainty = calibrated probability + split-conformal sets (class-conditional) + OOD flag +
   cross-family disagreement + data-quality grade.** The 90% "interval" attached to a probability
   is ensemble spread (model uncertainty) and is documented as such; the coverage-guaranteed
   statement is the conformal set. Conformal validity assumes exchangeability and is void under
   domain shift (Kepler -> TESS), which is what the OOD flag is for.
7. **CNN checkpointing uses validation log-loss, not PR-AUC.** On a few dozen validation rows
   PR-AUC is jumpy and selects an early lucky epoch (observed: train PR-AUC 0.57 < val 0.80);
   switching raised held-out PR-AUC from ~0.65 to 0.75-0.89 across seeds.
8. **Safe persistence.** GBM as LightGBM text, CNN as plain `state_dict` loaded with
   `weights_only=True`, datasets as `.npz` with `allow_pickle=False`. Registry versions are
   immutable and a model refuses to load against a different feature set.
9. **torch is an optional extra** (`uv sync --all-extras`). Everything except the CNN works
   without it; CNN tests `importorskip`.

## Honest limitations
- Everything measured so far is on SYNTHETIC data. It validates machinery (leakage guards,
  calibration/conformal code, registry round-trip), not scientific performance.
- Kepler DR25 labels (PC/AFP/NTP) are Robovetter outputs, so a model trained on them partly
  imitates that pipeline. The label noise is in the labels, not removable by modelling.
- Calibration gave no measurable ECE benefit on the small synthetic calibration set (mean ECE
  0.130 -> 0.128 over 40 re-splits). Brier is not degraded. Re-evaluate on real data (>=1000 rows
  lets `auto` choose isotonic).
- Stellar-context features (duration ratio, implied radius) are NaN until Phase 5 supplies
  Gaia/TIC parameters.
