.PHONY: setup dev up down test lint typecheck
setup:      ; uv sync --all-packages --all-extras  # torch is an optional extra
up:         ; docker compose -f infra/compose/docker-compose.yml up -d
down:       ; docker compose -f infra/compose/docker-compose.yml down
dev:        ; uv run uvicorn akash_api.main:app --reload --port 8000
test:       ; uv run pytest
lint:       ; uv run ruff check .
typecheck:  ; uv run mypy packages/akash_core/src packages/akash_provenance/src packages/akash_data/src packages/akash_science/src packages/akash_ml/src packages/akash_fusion/src

inject:     ; uv run python scripts/injection_recovery.py
live:       ; uv run pytest -m network tests/live
