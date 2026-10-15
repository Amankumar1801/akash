# ADR 0014: Spectrum analysis and stochastic-variability descriptors

Status: accepted

## Context
The blueprint's advanced modules cover spectra and AGN-style variability. Both are easy to oversell: a redshift from two
coincident lines can be chance, and variability does not identify what varies.

## Decision
- `akash_science.spectra`: numpy-only continuum estimate (running median), line detection against a robust noise estimate,
  and redshift candidates from lines that coincide with a fixed rest-line table.
  - A redshift is a candidate with its supporting lines. Status is one of `no_lines`, `single_line_only`, `no_match`,
    `candidate_redshift`, `ambiguous`. Tier is `tentative` (two lines) or `supported` (three or more). Nothing is "confirmed".
  - Broad emission (over 1,000 km/s) is reported as a descriptor. There is no AGN or object-type classification.
  - Invalid input (non-monotonic wavelength, too few or too many points, non-positive continuum) is rejected with a reason.
    Wavelengths are never re-sorted silently.
- `akash_science.agn`: excess variance with its error, a structure function, a damped-random-walk fit to it, and a periodicity
  test. Character is a closed enum: `insufficient_data`, `no_significant_variability`, `periodic_like`, `stochastic_aperiodic`.
  - The damping timescale is flagged unconstrained when the baseline is under ten times its value. One TESS sector
    (about 27 days) rarely allows more.
  - The periodicity test compares the peak against a fitted red-noise continuum (Vaughan 2005), not a white-noise false-alarm
    probability. A first version using the white-noise probability labelled plain red noise as periodic; the replacement gave 0
    false calls in 120 simulated red-noise series.
- API: `POST /v1/spectra/analyze` (20,000-point cap, audited by input hash only, never storing the spectrum) and
  `GET /v1/observations/{id}/variability` (flagged cadences dropped, provenance id and input hash returned).
- Frontend: a spectrum viewer, a variability panel on the investigation page, and a model detail view in the observatory.
  Demo mode ships one synthetic spectrum with an analysis precomputed by the Python code (`scripts/make_spectrum_fixture.py`)
  rather than a second implementation in TypeScript, and says so.

## Consequences
- Validated on synthetic spectra and simulated light curves only. Real spectra bring sky residuals, blends, calibration
  errors and lines outside the rest-line table, none of which are exercised here.
- The rest-line table is small (16 lines). Spectra without those lines will report no match.
- The structure function carries no per-bin errors, because neighbouring pairs are not independent.
