# ADR 0006: Cross-survey evidence, rule-based triage, and the investigation pipeline (Phase 5)
- Status: accepted

## Decisions
1. **One hypothesis fixes the meaning of "supports/contradicts".** H = "the detected signal is an
   astrophysical, planet-scale transit-like signal". SUPPORTS/CONTRADICTS describe how a finding
   bears on H; NEUTRAL is context; INCONCLUSIVE means the check could not decide. Nothing is
   summed or weighted anywhere, and `Assessment` still forbids an aggregate-score field.
2. **Every finding is an immutable typed `Evidence` row with real provenance.** Provenance roots are
   a source URI plus a content hash (catalog rows hash their query + values; an *empty* catalog
   result hashes the queries that returned nothing, because absence is a finding too).
   `verify_chain` is asserted for every row in the tests. The deterministic pipeline never emits
   INTERPRETATION evidence; that channel is reserved for the LLM/human (Phase 8).
3. **Triage is a fixed-precedence rule list, not a learned or probabilistic combiner.** There are no
   ground-truth outcomes to learn from and any prior would be an invented number. Precedence:
   known catalog match > insufficient data > hard vetting failure > corroborated systematics >
   several vetting warnings > models disagree > classifier excludes planet-like > new signal.
   Each decision carries reasons that cite evidence ids.
4. **A catalog match is by PERIOD, not by star.** A star hosting known TOIs can still show a new
   signal; matching on period (1%, plus 2x / 0.5x harmonics labelled as such) prevents "known
   star" from being mistaken for "known signal". Catalog status is reported, never decided.
5. **Contamination is a conservative capability test, not a probability.** A Gaia neighbour inside
   the aperture is "capable" if, even eclipsing fully, its share of the aperture flux >= the
   observed depth. It overstates contamination on purpose (no PSF weighting; Gaia G stands in for
   the survey band). It informs follow-up and conflicting evidence; it does not decide triage.
6. **Gaia parameters feed back into vetting.** Radius and logg reach the duration-plausibility and
   implied-radius checks, so a compact dwarf cannot "host" a 2.6 h transit at P=3.2 d (tested
   end to end).
7. **No transit signal => no Assessment.** The triage enum is closed and has no "no signal"
   member; inventing one would be a core-contract change. The investigation returns outcome
   `no_transit_signal` with its evidence (e.g. anomaly) still stored.
8. **Only the strongest TCE is triaged;** other periodic signals are recorded as NEUTRAL evidence.
9. **Missing inputs degrade explicitly.** A catalog or Gaia outage becomes an INCONCLUSIVE
   evidence row, a warning, and a follow-up, never a silent omission or a fake "no match".

## Mistakes found by reading real output, and fixed
- A WARN on a vetting check produced NO follow-up (the odd/even WARN case printed an empty list).
  Now every WARN/FAIL yields an action (tested for all seven checks).
- **A single-model system reported "ensemble spread 0.95-0.95"**, i.e. zero uncertainty, when the
  spread is undefined for one model (a Phase 3 scoring bug that only appeared when a system had
  one member). It now reports the vacuous interval [0, 1] ("unknown") and says so in the claim.
- Reused the name `e` for an exception handler and a loop variable in `investigate`; renamed.
- Cosmetic: duplicated version strings in the matrix; "(0 checked)" contamination wording.

## Known limitations (deliberately kept visible)
- **Equal-depth eclipsing binaries are photometrically degenerate with a planet at half the
  period.** Tested and pinned: the system reports NEW_SIGNAL_REVIEW with no conflicting evidence,
  because nothing in the light curve distinguishes them.
- **A single WARN is not decisive** (`n_warn_decisive = 2`, an unmeasured heuristic). A moderate
  binary (4000/3000 ppm) therefore stays in review with the concern shown as conflicting evidence
  and a follow-up. Whether the threshold should differ is a Phase 10 measurement.
- `LIKELY_SYSTEMATIC` also covers astrophysical false positives (eclipsing binaries); reasons name
  the mechanism. Renaming the enum value needs its own ADR.
- The classifier-rejection rule is a MODEL decision and is labelled as such in its reason text.
- Contamination uses a fixed 21" aperture (TESS); Kepler would need ~4". Catalog matching ignores
  epoch (period only).
- All of this is exercised on synthetic light curves with in-memory fake catalogs; live-archive
  behaviour (Phase 1 providers) is still unverified.
