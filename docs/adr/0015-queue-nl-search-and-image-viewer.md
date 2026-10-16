# ADR 0015: Durable job queue, natural-language search, image viewer

Status: accepted

## Decisions

**Durable queue.** The `job` table carries `lease_owner`, `lease_until` and `attempts`. A worker
claims one queued job atomically (`UPDATE ... RETURNING`), heartbeats while running, and a reaper
requeues jobs whose lease expired or fails them after `worker_max_attempts` with "the worker
stopped responding". `api_executor=queue` makes the API only enqueue; `python -m
akash_api.queue_worker` runs jobs. A retried job discards the partial evidence of the earlier
attempt. Orphan recovery on startup is skipped when the executor is external.

**Natural-language search.** A deterministic rule table (22 rules) turns a phrase into the same
filters the feed already accepts. No LLM. The reply lists what was understood, what is
unsupported and what was ignored, and the UI applies filters through the normal feed endpoint, so
every search is inspectable. The rules are exported to JSON and run by the frontend, with a parity
test over shared cases.

**Image viewer.** Deterministic photometry on a user-supplied FITS image or raw pixels: clipped
background, 3 sigma detection, centroid, flux, r20/r50/r80, concentration, asymmetry and second-
moment shape. It reports measurements and caveats and assigns no morphological class or redshift.

## Limits (honest)
- Postgres and object-storage ports are **not built** (no Postgres or S3 in the sandbox). Workers and
  the API must share one SQLite file and artifact directory, so this is multi-process on one node,
  not a scale-out.
- A stale worker that lost its lease can still call finish; the write is not owner-guarded. Experiments
  still run in-process.
- All of it is validated on synthetic data and fakes. `scripts/validate_real_targets.py` exists but
  has **never run** (no network).
- NL search covers only the phrases in the rule table. Image analysis is not a galaxy classifier.
- Docker images, including the new worker service, were never built.
