# Phase 2: injection-recovery results (SYNTHETIC noise)

**Read this first.** Base light curves are synthetic (white + AR(1) red noise + sinusoidal
variability, 27 d, 10-min cadence, one mid-sector gap). Injected signals are trapezoids.
This validates the pipeline's *mechanics and guards*. It does NOT measure sensitivity on real
TESS/Kepler data; that is the Phase 10 experiment.

Reproduce: `uv run python scripts/injection_recovery.py --trials 100 --controls 30 --seed 7`
(~15 min on CPU, single process). Recovery = a TCE within 1% of the injected period AND epoch
within one transit duration. Half/double-period hits are counted separately as aliases.
"Expected SNR" is the analytic matched-filter SNR of the injected signal, using the measured
white sigma inflated by the same red-noise factor beta the search applies.
Periods log-uniform 1-10 d, depths log-uniform 150-3000 ppm, duration = solar-density
duration x U(0.5, 1).

| Expected SNR | n | Recovered | Fraction | Aliases only |
|---|---|---|---|---|
| 0-3 | 30 | 0 | 0.00 | 0.00 |
| 3-5 | 19 | 0 | 0.00 | 0.00 |
| 5-7 | 12 | 3 | 0.25 | 0.00 |
| 7-9 | 12 | 6 | 0.50 | 0.00 |
| 9-12 | 8 | 8 | 1.00 | 0.00 |
| 12-16 | 6 | 6 | 1.00 | 0.00 |
| 16-25 | 10 | 10 | 1.00 | 0.00 |
| >25 | 3 | 3 | 1.00 | 0.00 |

- **Acceptance threshold (set after measurement): expected SNR >= 9.** 27/27 recovered. With
  27 trials the 95% Wilson lower bound on recovery is ~0.88, so "about 88% or better, on
  synthetic noise" is the defensible claim, not a flat "100%".
- The detection threshold is 7.1 (a convention). Recovery is 50% in the 7-9 bin and 25% in 5-7,
  i.e. the effective threshold sits near expected SNR ~8-9, above the nominal 7.1. This is
  expected: the red-noise factor and refinement make the reported SNR more conservative than
  the analytic one. Per-bin counts are small (6-30), so these fractions carry wide uncertainty.
- **Controls:** 0/30 un-injected curves produced a TCE (95% upper bound ~10%, rule of three).
  Without the duty-cycle cap and red-noise correction, noise-only data produced spurious TCEs
  (regression-tested: on red-noise-heavy data the unguarded search reports 3 TCEs at SNR 15-18
  where the guarded one reports none).
- **Period accuracy (recovered):** median fractional error 8.7e-5, 95th percentile 5.5e-4.
- No alias-only recoveries occurred in this run.

## Not yet measured
Empirical coverage of the reported period interval (it is a heuristic dlogL region and may
under-cover); depth bias from detrending; real-noise performance; dependence on stellar type
and cadence; vetting-check false-positive/negative rates on labelled data; per-bin uncertainty
beyond the Wilson bound above.
