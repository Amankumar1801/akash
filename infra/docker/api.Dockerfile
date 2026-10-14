# syntax=docker/dockerfile:1.7
# AKASH API. Build from the repository root:
#   docker build -f infra/docker/api.Dockerfile -t akash-api .
# Add the CNN classifier runtime (CPU torch, large) with --build-arg INSTALL_TORCH=true.

FROM python:3.12-slim AS build
ARG INSTALL_TORCH=false
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages packages
COPY services services
# --no-editable: the runtime image carries installed packages, not links into the source tree.
RUN uv sync --frozen --no-dev --no-editable --package akash-api
RUN if [ "$INSTALL_TORCH" = "true" ]; then \
      uv pip install --python .venv/bin/python torch --index-url https://download.pytorch.org/whl/cpu; \
    fi

FROM python:3.12-slim AS runtime
RUN useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin akash \
 && mkdir -p /data /models && chown akash:akash /data
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY scripts scripts
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    AKASH_ENV=prod AKASH_DATA_DIR=/data AKASH_SQLITE_PATH=/data/akash.sqlite3 \
    AKASH_REGISTRY_ROOT=/models
USER akash
EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=4 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/v1/ready', timeout=2).status==200 else 1)"
# ONE worker on purpose: jobs run in-process and orphan recovery assumes a single owner of the
# SQLite file. Scale vertically; see docs/deploy.md for what changes before scaling out.
CMD ["uvicorn", "akash_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--no-server-header", "--proxy-headers", "--timeout-graceful-shutdown", "20"]
