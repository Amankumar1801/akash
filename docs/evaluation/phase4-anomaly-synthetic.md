# Phase 4: anomaly engine, evaluated on SYNTHETIC light curves

**Read this first.** Every number here is from synthetic populations: ordinary variable stars
(sinusoidal + white/red noise + small flares) as the reference, and strongly injected anomalies.
It shows the machinery behaves correctly and exposes its failure modes. It does **not** say how
well real TESS/Kepler anomalies will be found: real noise, real systematics, and the real
choice of reference population (which *defines* "normal") are untested (Phase 10).

Reproduce (deterministic, ~4 min, 1 CPU; a re-run matched to every printed digit):
`uv run python scripts/evaluate_anomaly.py --test-seed 1700 --json evaluation/anomaly-synthetic.json`

## Protocol
- **Reference:** 450 ordinary stars. Detectors fit on ~80% of stars; the percentile mapping
  measured on the held-out ~20% (hash-assigned by star).
- **Validation (seed 300):** the detector-combination rule is chosen here, by mean per-kind
  detection at 5% false-positive rate. Result: `mean` 0.987, `top2` 1.000, `max` 1.000, so `top2`
  (simplest rule among the tied best).
- **Test (seed 1700):** 165 objects (60 ordinary, 15 each of 5 anomaly kinds and 2 artifact
  kinds), evaluated once with the rule fixed. Seeds 200 and 900 were used while iterating and
  are NOT clean (ADR 0005).

## Results (test)
| Kind | Detection at 5% FPR | Flagged as artifact |
|---|---|---|
| dimming (Boyajian-like) | 1.00 | 0.13 |
| eclipsing | 1.00 | 0.00 |
| flares | 1.00 | 0.00 |
| extreme amplitude | 1.00 | 0.13 |
| unusual (short) period | 1.00 | 0.00 |
| ordinary stars (the 5% FPR budget) | 0.05 | 0.00 |
| artifact: step + edge ramps | n/a | 1.00 |
| artifact: flagged cadences + spikes | n/a | 1.00 |

- **Per-kind perfect recovery means the synthetic anomalies are easy**, not that the engine is.
  With only 60 ordinary stars setting the 5% FPR threshold, the threshold itself is noisy.
- **Artifact gate:** 100% of artifacts flagged; 0% of ordinary stars; **5.3% of genuine anomalies
  wrongly flagged** (2/15 dimming, 2/15 extreme-amplitude). They are down-ranked with reasons
  shown, not hidden, but that is a real cost.
- **Top of the ranking** (by continuous severity; "gated" excludes artifact-suspect objects):

  | Top | k | Artifacts, ungated | gated | Precision (genuine anomaly) | Recall |
  |---|---|---|---|---|---|
  | 10% | 17 | 0% | 0% | 1.00 | 0.23 |
  | 20% | 33 | 0% | 0% | 1.00 | 0.44 |
  | 30% | 50 | **14%** | **0%** | 1.00 | 0.67 |

  The gate matters once the list extends past the most extreme objects. (Recall is capped by
  list length: there are 75 genuine anomalies, so a 17-item list can reach at most 0.23.)
- **Stability across two independently seeded engines:** Spearman 0.981, top-17 Jaccard 1.00.
- **Category agreement** (does the named category match the injected type): dimming 1.00,
  eclipsing 1.00, unusual period 1.00, flares 0.93, **extreme amplitude 0.31**. Large pulsations
  bleed into residual statistics and come out as "feature_combination_outlier".

## Why percentile alone is not used for ranking
AUROC with severity is 1.00; with percentile it is 0.98, and percentile-95 detection is only 0.60
for extreme amplitude and 0.80 for short period. Percentiles saturate and tie near 100, so
severity ranks the top of the list.

## What measuring caught (details in ADR 0005)
Artifact metric v1 flagged 33% of dimming stars and missed most steps; day-long dimmings were
invisible to a 1-day filter; fast variability needed a targeted feature (so its recovery is
partly a test of my own design); zero-inflated features were mis-scaled; and the combination rule
was first chosen with a criterion that tied across rules and hid a blind spot.

## Not yet measured
Real-noise behaviour; reference-choice sensitivity; false-flag rate of the artifact screen on
real systematics (TESS momentum dumps, scattered light); whether human reviewers find the top
of the list interesting (precision@K by review, Phase 10); sensitivity to reference size
(~90 held-out stars here); behaviour for stars unlike the whole reference (OOD for anomaly
scoring).
