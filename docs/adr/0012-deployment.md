# ADR 0012: Single-node deployment

Status: accepted (Phase 11)

## Decision
Ship what actually exists: one API process with in-process jobs and SQLite on a volume, behind nginx,
as two small images and one compose file. Do not present Postgres, Redis or Celery as part of the
deployment, because the API does not use them.

- **Fail fast in production.** `AKASH_ENV=prod` runs preflight at startup and refuses to start on
  errors (wildcard or non-https CORS, unwritable data directory, missing configured model or reference,
  a key without a model or over plain http, non-positive limits). Warnings are reported only. Findings
  never contain secret values.
- **Liveness and readiness are separate.** `/v1/health` says the process is up; `/v1/ready` also checks
  the database and returns 503 otherwise. The image healthcheck and compose `depends_on` use readiness.
- **One worker, deliberately.** In-process jobs, in-process rate limits and metrics, and orphan-job
  recovery all assume a single owner of the process and the SQLite file.
- **Hardened containers.** Non-root user, read-only root filesystem, all capabilities dropped,
  no-new-privileges, models mounted read-only, API not published (only nginx is), pinned tool versions.
- **nginx** serves the static UI with a strict CSP (no inline script, no remote assets), proxies `/v1`
  with buffering off (server-sent events), and keeps the UI same-origin so CORS stays off.
- **Backups are first-class**: online-consistent SQLite copy plus artifacts, hash manifest, verified
  restore, no overwrite by default, traversal-safe.

## Alternatives considered
- Postgres plus Celery plus Redis now: more moving parts, none exercised by the code, and a false
  claim of scalability. Deferred until a second instance is needed.
- Serverless or ephemeral-disk platforms: incompatible with SQLite-on-volume.
- Kubernetes: no requirement it would meet that one VM does not.

## Consequences and limits
- Vertical scaling only. A restart interrupts running jobs (they are marked failed, visibly).
- The images were not built in the authoring environment; CI is the first real build.
- No TLS in the stack by design; a terminator in front is required.
