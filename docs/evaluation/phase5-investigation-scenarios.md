# Phase 5: investigation scenarios (SYNTHETIC light curves, in-memory fake catalogs)

**Read this first.** Light curves are synthetic, and the Exoplanet Archive and Gaia are in-memory
fakes. This demonstrates the *logic* (rules, evidence, provenance) and its limits, not
astronomical performance. The classifier is a single GBM trained on synthetic TCEs, so its
probabilities carry no real-world meaning.

Reproduce: `uv run python scripts/demo_investigation.py --matrix "moderate eclipsing binary"`
(~40 s). Raw output: `evaluation/investigation-scenarios.json`.

| Scenario | Triage category | Decisive reason | Conflicting evidence | Follow-ups |
|---|---|---|---|---|
| clean planet | new_signal_review | no catalog match; vetting clean | 0 | none |
| known confirmed planet (period match) | known_confirmed | catalog_period_match:exact | 0 | none |
| known false positive (period match) | known_false_positive | catalog_period_match:exact | 1 | none |
| star has OTHER catalog entries | new_signal_review | no_catalog_match (states the star hosts others) | 0 | none |
| catalog outage | new_signal_review | catalog_unavailable (novelty UNVERIFIED) | 0 | re-check catalogs |
| nearby source could cause it | new_signal_review | (informs, does not decide) | 1 | centroid / difference imaging |
| compact dwarf, impossible duration | likely_systematic | vetting_fail:duration_plausibility | 1 | re-check stellar parameters |
| high-contrast eclipsing binary (2% / 1.5%) | likely_systematic | vetting_fail:odd_even | 2 | compare odd/even; depth consistency; classifier inputs out-of-distribution (rely on vetting) |
| moderate eclipsing binary (0.4% / 0.3%) | new_signal_review | single odd/even WARN not decisive | 1 | compare odd/even depths |
| equal-depth binary (0.4% / 0.4%) | new_signal_review | **indistinguishable from a planet at P/2** | 0 | none |
| no transit signal | (no assessment) | outcome `no_transit_signal` | n/a | n/a |

## What this shows
- A catalog match inherits the catalog's disposition and beats every other rule, and the evidence
  row says the status is reported, not decided.
- Cross-survey evidence changes outcomes only where it is physically decisive: Gaia radius/logg
  reach the vetting checks (compact dwarf), while a possible contaminant only adds conflicting
  evidence and an action.
- Outages are findings, not omissions.

## What it does NOT show / the honest limits
- The equal-depth binary row is a **fundamental degeneracy of photometry**, not a defect: no
  evidence exists in the data to flag it.
- The moderate binary stays in `new_signal_review`. The concern is visible and actionable, but a
  reviewer, not the rules, has to act on it. `n_warn_decisive = 2` is an unmeasured heuristic.
- Seven scenarios were hand-built by me; they cover cases I thought of. Real failure modes
  (TESS momentum dumps, scattered light, crowded fields, real catalog quirks) are untested.
- Model probabilities here (0.74-0.95 for real-looking signals, 0.03 for the strongest binary)
  come from a toy classifier and should not be read as calibrated astronomy.
