# ADR 0007: Backend API, durable jobs, and security (Phase 6)
- Status: accepted

## Decisions
1. **FastAPI app factory, no import side effects.** `create_app(settings, services)` takes an
   explicit service container (`AppServices`) so tests inject fakes and production injects real
   providers. `akash_api.main.app` is a lazy proxy that builds the production app on the first
   ASGI event; importing the module touches no database, directory, or network.
2. **One error envelope.** Every failure is `{"error": {"code", "message", "request_id", ...}}`.
   Validation errors never echo submitted values. Unhandled exceptions become a generic
   `internal_error`; details go to the server log only.
3. **Investigations are asynchronous, durable jobs.** `POST /v1/investigations` returns 202 with a
   job id. `JobStore` (SQLite, WAL) holds jobs and an append-only ordered event log with an atomic
   per-job `seq`. Idempotency is a partial unique index per owner, so a retried request returns the
   existing job (200, `deduplicated=true`). On startup, jobs left queued/running by a dead process
   are marked failed (orphan recovery).
4. **Executor behind a protocol.** `InProcessExecutor` (bounded thread pool) implements
   `JobExecutor`. A Celery/Redis executor is intended to replace it without touching routers; it is
   **not built or tested**.
5. **Progress is a first-class pipeline output.** `investigate(progress=...)` emits
   started/completed/failed/skipped per phase. The callback may raise `JobCancelled`, which aborts
   before anything is persisted. Results are identical with progress on or off (tested).
6. **SSE with resume, plus polling.** `/events` honours `Last-Event-ID` and replays from the event
   log; `/log` is a plain polling fallback. Streams end on a terminal event or a max duration.
7. **Authentication and authorisation.** Keys are `akash_<key_id>_<secret>`; only a sha256 of the
   secret is stored and compared in constant time. Roles are ordered viewer < researcher < admin.
   Other users' jobs return **404, not 403**, so ids cannot be enumerated. All auth decisions and
   job actions go to an audit table that never contains credentials.
8. **Per-principal token-bucket rate limits**, with a tighter bucket for investigations.
9. **Pure-ASGI security middleware.** Request id (client-supplied ids are sanitised), body-size
   limit enforced for both Content-Length and chunked bodies (413), security headers, and an access
   log without credentials or query strings.
10. **Job errors are sanitised.** Upstream failures become a fixed message, other `AkashError`s are
    truncated, and unexpected exceptions become "internal error (see server logs)".
11. **Model registry endpoints are read-only** and only expose name/version directories that match
    a strict pattern and resolve inside the registry root.
12. **Docs and CORS are opt-in.** OpenAPI docs only when `env == "dev"`; CORS off unless origins
    are configured.

## Consequences / known limits
- Single-process job execution and SQLite are fine for one node; they are not a scaling story.
- Nothing here was exercised against real Celery, Redis, Postgres, or live archives. The sandbox
  has none of them; all API tests use in-process fakes (`FakeResolver`, `FakeSource`).
- Rate limiting and key storage are per-process/per-database; multi-node needs shared state.
- Agent-facing tool permissions and prompt-injection defences are Phase 8, not this phase.
