"""Worker process: claims queued investigations from the shared database and runs them.

    AKASH_API_EXECUTOR=queue python -m akash_api.queue_worker

Several workers can share one database. A worker holds a lease on its job and renews it while it
works; if the worker dies, the lease expires and another worker (or this one, on its next poll)
requeues the job, up to `worker_max_attempts`, then marks it failed. Cancellation works across
processes because the job reads its cancel flag from the database."""

from __future__ import annotations

import logging
import os
import signal
import threading
import uuid
from collections.abc import Callable

from .jobs import JobStore
from .services import AppServices
from .worker import execute_job

log = logging.getLogger("akash.queue_worker")


def run_worker(services: AppServices, worker_id: str | None = None, *, max_jobs: int | None = None,
               stop: threading.Event | None = None,
               run: Callable[[AppServices, str], None] | None = None) -> int:
    """Poll, claim and run jobs until `stop` is set or `max_jobs` have been handled."""
    s = services.settings
    wid = worker_id or f"{os.uname().nodename}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    stop = stop or threading.Event()
    runner = run or (lambda sv, jid: execute_job(sv, jid, claimed=True))
    handled = 0
    while not stop.is_set() and (max_jobs is None or handled < max_jobs):
        with services.context() as ctx:
            store = JobStore(ctx.conn)
            for jid, what in store.reap_expired(s.worker_max_attempts):
                log.warning("job %s %s after a lost lease", jid, what)
            claimed = store.claim_next(wid, s.worker_lease_s)
        if claimed is None:
            stop.wait(s.worker_poll_s)
            continue
        job, attempt = claimed
        log.info("worker %s took job %s (attempt %d)", wid, job.job_id, attempt)
        done = threading.Event()

        def beat(job_id: str = job.job_id, done: threading.Event = done) -> None:
            while not done.wait(max(s.worker_lease_s / 3.0, 0.05)):
                with services.context() as bctx:
                    if not JobStore(bctx.conn).heartbeat(job_id, wid, s.worker_lease_s):
                        log.error("worker %s lost its lease on %s", wid, job_id)
                        return

        t = threading.Thread(target=beat, daemon=True, name="akash-heartbeat")
        t.start()
        try:
            runner(services, job.job_id)
        finally:
            done.set()
            t.join(timeout=5)
        handled += 1
        services.metrics.inc("worker_jobs_total", {"worker": "queue"})
    return handled


def main() -> None:  # pragma: no cover  (process entry point)
    from akash_core.config import Settings
    from akash_core.preflight import enforce

    from .services import build_default_services

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    enforce(settings)
    services = build_default_services(settings)
    services.ensure_schema()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    log.info("worker started (lease %.0fs, %d attempts)", settings.worker_lease_s,
             settings.worker_max_attempts)
    run_worker(services, stop=stop)


if __name__ == "__main__":  # pragma: no cover
    main()
