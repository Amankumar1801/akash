# AKASH: AI Astronomical Discovery Engine

Evidence-assembly platform for astronomical objects: real data, scientific ML, anomaly
detection, cross-survey evidence, explainability, uncertainty, and provenance.
**AKASH assists investigation; it does not independently establish discoveries.**

## Status
Phase 0 complete: workspace, CI, local stack, core schemas. Next: Phase 1 (data layer).

## Quickstart
```bash
make setup      # uv sync
make test       # core + api tests
make up         # postgres, redis, minio, mlflow (optional in Phase 0)
make dev        # API on :8000  ->  GET /v1/health
```

## Layout
- `packages/akash_core`: schemas, enums, ids, config (no web/ML deps)
- `services/api`: FastAPI service (thin routers)
- `docs/adr`: architecture decision records
- `infra/compose`: local dependencies
