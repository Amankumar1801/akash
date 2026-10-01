# ADR 0002: Data-layer contracts, local metadata store, and fixture strategy
- Status: accepted

## Decisions
1. **Three provider roles**, not one fat interface: name resolution (SIMBAD), catalog lookup
   (Gaia, NASA Exoplanet Archive), and observation retrieval (MAST TESS/Kepler). A provider
   implements only the roles it has.
2. **Gaia DR3 source ID is the cross-survey anchor.** If SIMBAD lists it, we adopt it; otherwise we
   cone-match after propagating the SIMBAD position to the Gaia epoch (2016.0) using proper
   motion. Ambiguous matches are *recorded* (`CrossmatchLink.ambiguous`) but never adopted,
   and ambiguous user queries raise `AmbiguousIdentity` with candidates instead of guessing.
   Thresholds (`clear_winner`) are heuristics; they are unit-tested but not scientifically tuned.
3. **Artifacts are immutable and content-addressed (sha256)**; reads verify the hash; corrupt or
   invalid files are quarantined, not deleted. Every stored observation must have a provenance
   chain whose root has `source_uri` and `sha256` (`verify_chain`).
4. **SQLite is the Phase 1 metadata/provenance store** behind small repository classes. The
   Postgres adapters arrive with the API (Phase 6). Schema is deliberately simple to port.
5. **Native quality flags are preserved verbatim**; mapping to a shared enum is deferred to the
   Phase 2 quality filter so no information is lost at ingestion.
6. **Fixtures**: unit tests use `httpx.MockTransport` with hand-authored responses in the
   *documented* shapes and synthetic FITS in the documented SPOC/Kepler layout. These prove our
   logic, **not** that our assumptions about live schemas are right. `scripts/record_fixtures.py`
   and `pytest -m network` exist to close that gap and must be run before relying on providers.

## Known limitations
- SIMBAD name lookup uses exact `ident.id` matching (no fuzzy/case-insensitive search).
- Objects resolved without a TIC/KIC alias fall back to positional MAST matching, flagged
  `identity_match=positional` on each observation.
- Only SPOC (TESS) and Kepler LC products are supported; QLP/FFI and SDSS are later providers.
