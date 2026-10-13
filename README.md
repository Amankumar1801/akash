# AKASH: AI Astronomical Discovery Engine

Evidence-assembly platform for astronomical objects: real data, scientific ML, anomaly
detection, cross-survey evidence, explainability, uncertainty, and provenance.
**AKASH assists investigation; it does not independently establish discoveries.**

## Status
- **Phase 0** complete: workspace, CI, core schemas.
- **Phase 1** complete in code (identity resolver, SIMBAD/Gaia/Exoplanet Archive/MAST TESS+Kepler
  providers, caching, retries, validation, provenance), **pending live verification** against the
  real archives: `uv run pytest -m network tests/live` (see ADR 0002).
- **Phase 2** complete on **synthetic** data (quality, detrending, BLS search, views, vetting v1,
  injection-recovery; see ADR 0003 and docs/evaluation). Real-data sensitivity is a Phase 10
  measurement.
- **Phase 3** complete on **synthetic** data (classifier system, grouped frozen splits,
  calibration, conformal sets, OOD, registry, model card; ADR 0004). Real training needs the Kepler
  DR25 table + light curves: see `scripts/build_kepler_training_set.py`, `scripts/train_transit.py`.
- **Phase 4** complete on **synthetic** data (variability/artifact features, 4-detector ensemble with
  held-out calibration, artifact gate, severity ranking; ADR 0005, docs/evaluation). A real reference
  population must be curated: `scripts/build_anomaly_reference.py`.
- **Phase 5** complete on **synthetic** data with fake catalogs (typed evidence with provenance, Gaia
  enrichment + contamination, period-based catalog matching, rule-based triage, evidence matrix,
  `investigate()`; ADR 0006, docs/evaluation/phase5-investigation-scenarios.md). Live archives untested.
- **Phase 6** complete on in-process fakes (FastAPI service: object search, observations, async
  investigations with durable jobs, SSE + polling progress, cancel/idempotency, API-key auth with
  roles, rate limits, audit log, model registry endpoints; see ADR 0007). Not tested against real
  Celery/Redis/Postgres or live archives.
- **Phase 7** (first slice) complete: React frontend in `frontend/` (logbook, live investigation view, light/folded curves, separate readouts, evidence strip, provenance graph, models; ADR 0008). Runs on synthetic demo data or the Phase 6 API; the live path is tested only against a local HTTP server.
- **Phase 8** complete: read-only, bounded research agent (`packages/akash_agent`, ADR 0009) with prompt-injection defences, a citation verifier and a deterministic fallback; `POST /v1/investigations/{id}/ask` and an Ask tab. No live LLM has been exercised; the provider is tested against a mock transport only.
- **Phase 9** complete: deterministic 13-section scientific reports (`packages/akash_report`, ADR 0010) with Markdown/HTML export, `POST /v1/reports` and a Report tab. Built from stored evidence only; no model writes any of it. No PDF output; the demo-mode report is a shorter client-side version.
- **Phase 10** complete: injection-recovery experiment lab (`packages/akash_eval`, `/v1/experiments`, Lab page) with Wilson intervals and explicit synthetic-noise caveats; metrics (`/v1/metrics`) and per-investigation traces; human review labels with an export for active learning (ADR 0011). Sensitivity is measured on synthetic noise only; metrics are per-process; nothing retrains automatically.

## Quickstart
```bash
make setup      # uv sync --all-extras (includes torch)
make test       # core + api tests
make up         # postgres, redis, minio, mlflow (optional in Phase 0)
make dev        # API on :8000  ->  GET /v1/health
```

## Layout
- `packages/akash_core`: schemas, enums, ids, config (no web/ML deps)
- `packages/akash_data`: identity, providers, storage, ingestion
- `packages/akash_ml`: transit classifier (LightGBM + 1D CNN), calibration, conformal, OOD, registry,
  and the anomaly engine (`anomaly/`: detectors, autoencoder, reference populations)
- `packages/akash_fusion`: cross-survey evidence, rule-based triage, assessments, investigation pipeline
- `packages/akash_science`: deterministic light-curve science (no ML deps)
- `packages/akash_provenance`: provenance records + lineage
- `services/api`: FastAPI service (thin routers)
- `docs/adr`: architecture decision records
- `infra/compose`: local dependencies
