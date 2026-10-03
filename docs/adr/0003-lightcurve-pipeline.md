# ADR 0003: Light-curve pipeline design (Phase 2)
- Status: accepted

## Decisions
1. **Detection is deterministic; ML only classifies.** BLS (astropy) finds threshold-crossing
   events; no neural net searches raw light curves. Matches mission-pipeline practice and keeps
   every number explainable.
2. **Own biweight detrender instead of `wotan`.** ~60 lines of numpy, gap-aware, evaluated on a
   coarse grid and interpolated, with transit masking on pass 2. Avoids a dependency whose
   behaviour we would need to re-verify anyway. Revisit if profiling or accuracy demands it.
3. **Clipping is upward-only.** A transit is a dip; the clip can never remove one
   (regression-tested with a 2% deep transit).
4. **BLS needs two guards or it fails on red noise** (found empirically in Phase 2: a spurious
   P=0.62 d / T=0.3 d "signal" with SNR 9.3 in noise-only data):
   (a) duty-cycle cap `duration/period <= 0.15`;
   (b) SNR divided by a Pont-et-al.-style red-noise factor beta >= 1, and beta also inflates
       the period interval and the odd/even, secondary, and per-transit tests.
5. **Vetting checks are independent and never averaged.** Each returns PASS/WARN/FAIL/UNKNOWN
   with its metrics. A check that raises degrades to UNKNOWN. Checks needing stellar context
   (duration plausibility, implied radius) return UNKNOWN until Gaia/TIC data is supplied in
   Phase 5. Thresholds are heuristic module constants, to be tuned in Phase 10.
6. **Transit-shape check is a chi^2 model comparison** (flat vs V over a T14 x ingress-fraction
   grid), not a depth ratio inside the BLS box (that metric depended on which box width BLS
   picked and failed on triangles).
7. **Period interval** is an approximate dlogL = 0.5*beta^2 region on a fine grid. It is
   indicative, not a calibrated confidence interval; its empirical coverage should be measured
   in the injection lab before it is shown to users as a "95%" anything.
8. **Injection uses a trapezoid model on synthetic light curves.** This measures the pipeline's
   mechanics, NOT sensitivity on real TESS/Kepler noise. Real-noise injection and a
   limb-darkened (batman) model are Phase 10.

## Known behaviours worth knowing
- BLS can lock onto half the true period of an eclipsing binary (primary and secondary
  alternate); the odd/even check then rejects it. This is the intended safety net.
- Native quality flags: default policy drops every flagged cadence (`allowed_quality_bits=0`).
  Per-bit tuning waits for real-data review.

## Addendum: fine refinement of the BLS peak (found and fixed during Phase 2)
- The coarse BLS grid is too coarse: a ~0.03% period error slides the fold by ~25% of a
  transit duration over 8 cycles, which made per-transit depths look inconsistent
  (`periodicity_coverage` WARN on a clean injection). The search now refines (P, duration, t0)
  on a fine grid (+-0.5% in P, oversample 20) around the coarse peak, and everything downstream
  uses the refined values.
- **Invariant:** the *final* reported SNR is always `depth_snr / beta`, recomputed at the refined
  parameters. A first version of the refinement recomputed SNR without beta, silently disabling
  the red-noise guard; `test_red_noise_guard_applies_to_final_reported_snr` now pins this.
- Eclipsing binaries may yield two TCEs (the true period, flagged by the secondary-eclipse check,
  and the half period, flagged by odd/even). Tests assert the binary is flagged either way
  rather than assuming which period BLS locks onto.
