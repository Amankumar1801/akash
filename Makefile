.PHONY: setup dev up down test lint typecheck
setup:      ; uv sync --all-packages
up:         ; docker compose -f infra/compose/docker-compose.yml up -d
down:       ; docker compose -f infra/compose/docker-compose.yml down
dev:        ; uv run uvicorn akash_api.main:app --reload --port 8000
test:       ; uv run pytest
lint:       ; uv run ruff check .
typecheck:  ; uv run mypy packages/akash_core/src
