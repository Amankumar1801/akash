"""Runs one investigation job. Every failure becomes a visible, sanitized job state; internal
exceptions are logged in full server-side but never leak to the client."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from akash_core.errors import AkashError, JobCancelled, ProviderError
from akash_fusion.assembler import investigate
from akash_fusion.progress import ProgressEvent

from .jobs import CANCELLED, FAILED, SUCCEEDED, JobStore
from .services import AppServices

log = logging.getLogger("akash.worker")
MAX_ERROR_CHARS = 300


def sanitize(e: BaseException) -> str:
    """What the CLIENT may read in `job.error`. Same rule as the HTTP error handlers: domain
    errors carry safe messages; upstream failures (hostnames, URLs, status bodies) and unexpected
    exceptions stay in the server log."""
    if isinstance(e, ProviderError):
        log.warning("upstream failure in job: %s", e)
        return "ProviderError: an upstream archive request failed"
    if isinstance(e, AkashError):
        return f"{type(e).__name__}: {str(e)[:MAX_ERROR_CHARS]}"
    return "internal error (see server logs)"


def execute_job(services: AppServices, job_id: str) -> None:
    with services.context() as ctx:
        jobs = JobStore(ctx.conn)
        job = jobs.get(job_id)
        if job is None or job.terminal:
            return
        if job.cancel_requested or not jobs.mark_running(job_id):
            jobs.finish(job_id, CANCELLED)
            jobs.append_event(job_id, "job_cancelled", {})
            return
        jobs.append_event(job_id, "job_started", {"trace_id": job_id})

        def check_cancel() -> None:
            if jobs.cancel_requested(job_id):
                raise JobCancelled("cancellation requested")

        def progress(ev: ProgressEvent) -> None:
            check_cancel()
            jobs.append_event(job_id, "phase", {"phase": ev.phase, "status": ev.status,
                                                "message": ev.message, "data": ev.data})

        p: dict[str, Any] = job.params
        try:
            obj = ctx.repo.get_object(UUID(p["object_id"]))
            if obj is None:
                raise AkashError("object no longer exists")
            progress(ProgressEvent("fetch_data", "started", f"{p['mission']} light curves"))
            bundle = services.make_lightcurve_source(ctx).fetch(
                obj, p["mission"], list(p["segments"]), int(p["max_observations"]))
            progress(ProgressEvent("fetch_data", "completed",
                                   f"{bundle.n_observations} observation(s)",
                                   {"n_observations": bundle.n_observations,
                                    "warnings": bundle.warnings[:5]}))
            result = investigate(obj, bundle.lc, bundle.prov_id,
                                 services.make_investigation_deps(ctx, p["mode"]),
                                 UUID(job_id), progress)
            category = result.assessment.triage_category.value if result.assessment else None
            jobs.finish(job_id, SUCCEEDED, outcome=result.outcome, category=category)
            jobs.append_event(job_id, "job_succeeded", {"outcome": result.outcome,
                                                        "category": category,
                                                        "warnings": result.warnings[:10]})
        except JobCancelled:
            jobs.finish(job_id, CANCELLED)
            jobs.append_event(job_id, "job_cancelled", {})
        except Exception as e:  # noqa: BLE001  (a job must always end in a terminal state)
            if not isinstance(e, AkashError):
                log.exception("job %s crashed", job_id)
            msg = sanitize(e)
            jobs.finish(job_id, FAILED, error=msg)
            jobs.append_event(job_id, "job_failed", {"error": msg})
