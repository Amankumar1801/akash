# ADR 0005: Anomaly engine (Phase 4)
- Status: accepted

## Wording contract
A high score means "unusual relative to <named reference population>; requires investigation".
It never means "discovery" or "new object". Every result carries the reference id; the engine's
interpretation text is tested to never contain discovery language.

## Decisions
1. **Quality gate first, artifact screen second, score third.** Light curves too short/degraded
   (grade D) are returned as `insufficient_data` and never scored. Artifact-suspect objects are
   scored (so the numbers are visible) but get `review_priority = None` and the reasons attached.
2. **Four detectors, shown separately, combined by percentile rank, never raw score**:
   Isolation Forest and LOF on 26 variability/dip/flare/periodicity features; autoencoder
   reconstruction error (unusual *shape*); latent-space kNN distance. Raw scores have
   incompatible scales.
3. **Reference defines "normal", with held-out calibration.** Detectors are fit on ~80% of
   reference *stars*; the percentile mapping is measured on the other ~20% (hash-assigned). Scoring
   the stars a detector was fit on makes the reference look artificially normal.
4. **Rank by a continuous `severity`, report percentile for context.** Percentiles saturate at
   100 and tie (with ~90 held-out stars they also have ~1% resolution), making top-K lists and
   cross-seed stability arbitrary. Severity = distance into the tail in reference-spread units.
5. **Detector-combination rule is chosen on a separate validation population**, by mean
   per-kind detection at 5% FPR (default `top2`). See "Mistakes" below for why not AUROC.
6. **Artifact metrics are normalised by the star's own variability.** A step is a persistent level
   offset across a data gap divided by how much *this star* changes over the same lag (90th
   percentile of window-to-window changes). Ratio thresholds adapt to the reference (p99.5,
   floor 2.0); flagged-cadence thresholds are absolute.
7. **Deterministic extraction lives in `akash_science` (torch-free); detectors in `akash_ml`.**
8. **Persistence without pickle.** A reference stores its data + autoencoder `state_dict`;
   Isolation Forest / LOF / kNN are refit deterministically on load and the saved score-
   distribution fingerprint must be reproduced exactly or loading fails.

## Mistakes made and fixed during this phase (kept because they bear on trust)
- **Artifact metric v1 was wrong.** It flagged 33% of dimming stars (a real dip next to a data
  gap looks like a step) and missed most steps; the ramp metric missed ramps because the 1-day
  detrend absorbed them. Replaced by structure-function-normalised metrics (decision 6).
- **Dips wider than the detrend window were invisible.** Boyajian-like day-long dimmings were
  absorbed by the 1-day filter; added 4-day "slow dip" features.
- **Fast variability was missed**, not by a bug but because high residual periodogram power and
  short residual period each occur separately in ordinary stars; only their conjunction is
  anomalous, which generic detectors in ~26-D with ~360 fit points cannot isolate. Added a
  targeted feature (residual power at periods <0.6 d). NOTE this feature was added after
  observing the miss, so recovery of that class is partly a test of my own design.
- **z-score floor bug**: zero-inflated features (dip/flare counts have MAD = 0) were floored at
  scale 1 and out-voted by amplitude features, skewing every category; now falls back to std.
- **Model-selection bug.** I first chose the combination rule by pooled AUROC, which tied at
  1.000 for all rules (dict order then decided) while per-kind detection differed enormously
  (mean 0.52 vs max 0.99). `mean` dilutes anomalies only some detectors can see: the autoencoder
  works on amplitude-normalised shapes, so it is blind to amplitude. Fixed (decision 5).
- **Test-set contamination.** Seeds 200 and 900 were examined repeatedly while iterating, so they
  are development data. Final numbers use a fresh seed (1700) never examined before the
  protocol was frozen.

## Honest limitations
- All evidence is on SYNTHETIC light curves with strong, distinct injected anomalies; perfect
  per-kind recovery shows the machinery works, not that real anomalies will be this separable.
- Category labels are weak for large-amplitude variability (31% agreement): big pulsations bleed
  into residual statistics and come out as "feature_combination_outlier".
- The artifact screen wrongly flags ~5% of genuine anomalies (they are down-ranked, not hidden).
- Real light-curve noise, TESS systematics, and real reference choices (the thing that defines
  "normal") are untested here; that is Phase 10.
