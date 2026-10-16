# Deploying AKASH

This is a single-node deployment: one API process (jobs run in-process, state in SQLite on a
volume) behind nginx. That is the honest scale of what is built. It is enough for a portfolio demo,
a lab, or a small team. The section on scaling out says what has to change first.

## Environments
| | Local dev | Staging | Production |
|---|---|---|---|
| Run | `make api` and `make web` (Vite proxy), demo data works with no API | the production compose file on a small VM | the same compose file, `AKASH_ENV=prod` |
| Data | `./data`, synthetic fixtures, offline tests | real archives, throwaway volume | real archives, backed-up volume |
| Config check | warnings only | `AKASH_ENV=staging`, run preflight | `AKASH_ENV=prod` **refuses to start** on a bad config |
| LLM | none (deterministic agent) | optional, spend-capped key | optional, spend-capped key |

Promote the same image through all three; only the environment file changes.

## First deployment
1. `cp infra/compose/prod.env.example .env` and edit (contact email, model paths, optional LLM key).
2. Put trained models in `./models` (read-only mount at `/models`) and set `AKASH_TRANSIT_MODEL=name/version`.
   Without a model the classifier is off and investigations say so.
3. `docker compose -f infra/compose/docker-compose.prod.yml --env-file .env up -d --build`.
4. Create the first admin key (printed once, stored hashed):
   `docker compose -f infra/compose/docker-compose.prod.yml exec api python scripts/create_api_key.py --name you --role admin`
5. Put TLS in front of port 8080 (Caddy is the least work: `reverse_proxy localhost:8080`). Nothing here
   terminates TLS, so do not expose 8080 directly to the internet.
6. Check: `/v1/health` (alive), `/v1/ready` (can serve), and `/v1/metrics?format=prometheus` with the admin key.

`scripts/preflight.py` runs the same checks the service runs at startup; use it in CI or before a deploy.

## Image size
The API image has no torch by default (the LightGBM classifier needs none). The 1D-CNN member needs it:
rebuild with `--build-arg INSTALL_TORCH=true`. That installs CPU torch and adds roughly 1 GB.

## Backup and restore
`scripts/backup.py create` writes one tar.gz with a consistent online copy of the database, every
artifact, and a manifest of sha256 hashes. Restore verifies all hashes and the database integrity
before writing anything, refuses unsafe archive members, and will not overwrite unless asked. Stop the
API before restoring. Schedule the backup (cron on the host, `docker compose exec api ...`) and copy
archives off the machine. **An untested backup is not a backup: restore one into a scratch volume
before you rely on it.**

## Upgrades and rollback
Images are tagged by commit. Upgrade by building the new tag and `up -d`. The idempotency key includes
the pipeline version and model, so new code or a new model produces new results instead of replaying old
ones. Take a backup first. Roll back by starting the previous tag; the database only gains tables, but
test that on staging before relying on it.

## Secrets
`.env` is git-ignored and docker-ignored. API keys are stored hashed. The LLM key is read from the
environment, never logged, and never included in errors. Use a provider key with a spend cap.

## Low-cost hosting
- One small VM (2 vCPU, 2 to 4 GB) with Docker and Caddy: the simplest fit for this design.
- A PaaS that runs a container with a persistent volume works (the volume is required: SQLite and artifacts live there).
- Platforms with ephemeral disks, or that run several instances, do **not** fit yet.

## Worker process (queue executor)
Set `AKASH_API_EXECUTOR=queue` on the API and run one or more `worker` containers
(`python -m akash_api.queue_worker`). They claim jobs with a lease (`AKASH_WORKER_LEASE_S`, default 60),
heartbeat while running, and a crashed worker's job is requeued up to `AKASH_WORKER_MAX_ATTEMPTS` times.
All processes must mount the **same** data volume: this is SQLite on one node, not a distributed
queue. Preflight warns if the queue is selected; make sure a worker is actually running, otherwise
jobs stay queued forever.

## Scaling out (not built)
Before running more than one API instance, replace: in-process executors with a queue and workers (Celery/Redis
or similar), SQLite with Postgres, local artifacts with object storage, and in-process metrics and rate limits
with shared ones. `infra/compose/docker-compose.yml` holds scaffolding for those services; the API does not use
them today. Orphan-job recovery on startup assumes a single process owns the database.

## What has not been exercised
The Dockerfiles, nginx config and compose file were written and statically checked (compose parses, safety
properties are asserted by `tests/test_infra.py`), but the images were **not built or run** in the environment
where this was written (no Docker daemon). The CI `images` job builds both images and smoke-tests the API
container; treat the first green run of that job as the real acceptance test.
