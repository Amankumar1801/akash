# Real-data validation

**Status: run once on a networked machine.** WASP-18 b, pi Men c and TOI-270 c passed. Kepler-10 b
failed because Kepler files name the quality column `SAP_QUALITY`; that is fixed and covered by
regression tests, and the target should be re-run to confirm on live data. All other AKASH results
were obtained on synthetic light curves or in-memory fakes.

## Run it

On a machine with internet access (MAST, NASA Exoplanet Archive, Gaia):

    uv sync
    uv run python scripts/validate_real_targets.py --json validate.json

It resolves four well-known targets, downloads up to three light curves each, runs the full
"deep" investigation, and compares the recovered period and depth with rounded published values.
Exit code 0 means every target was within tolerance.

## What a row means

| status | meaning |
|---|---|
| ok | period within 2% and depth within a factor of 2 of the reference |
| period_mismatch | wrong period, including 2x/0.5x aliases; inspect the folded curve |
| depth_mismatch | right period, depth off by more than 2x (often detrending) |
| no_transit | the pipeline found no transit; the note gives the outcome |
| error | fetch or pipeline failure; the note gives the exception |

## Limits

- Reference values are approximate and hand-rounded; edit `REFERENCE` with values from the
  NASA Exoplanet Archive before drawing conclusions.
- Four targets cannot measure false-positive or recall rates. For that, use
  `scripts/injection_recovery.py` on real light curves and `scripts/evaluate_anomaly.py`.
- A pass is a smoke test of the real-data path (adapters, normalisation, detrending, search).
- Record real responses with `scripts/record_fixtures.py` to turn a successful run into offline
  regression tests.
