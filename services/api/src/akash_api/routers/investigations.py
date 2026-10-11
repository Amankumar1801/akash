from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

from akash_core.ids import job_key
from akash_fusion.matrix import evidence_matrix
from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..auth import Principal, Role
from ..db import StoreContext
from ..deps import audit, authorized_job, get_ctx, get_services, rate_limited, require
from ..errors import ApiError
from ..jobs import CANCELLED, QUEUED, SUCCEEDED, TERMINAL_EVENT_KINDS, Job, JobStore
from ..schemas import (
    EventOut,
    InvestigationOut,
    InvestigationRequest,
    JobOut,
    ProvEdge,
    ProvenanceGraphOut,
    ProvNode,
)
from ..services import AppServices
from ..worker import execute_job

router = APIRouter(prefix="/v1")
READ = [Depends(rate_limited("general", "api_rate_per_min"))]
WRITE = [Depends(rate_limited("investigation", "api_investigation_rate_per_min"))]


def _links(job_id: str) -> dict[str, str]:
    base = f"/v1/investigations/{job_id}"
    return {"self": base, "events": f"{base}/events", "log": f"{base}/log",
            "evidence": f"{base}/evidence", "provenance": f"{base}/provenance"}


def _job_fields(job: Job, deduplicated: bool = False) -> dict[str, Any]:
    return dict(investigation_id=UUID(job.job_id), status=job.status, created_at=job.created_at,
                started_at=job.started_at, finished_at=job.finished_at, error=job.error,
                outcome=job.outcome, category=job.category,
                cancel_requested=job.cancel_requested, deduplicated=deduplicated,
                links=_links(job.job_id))


@router.post("/investigations", status_code=202, response_model=JobOut, dependencies=WRITE)
def create_investigation(body: InvestigationRequest, request: Request,
                         principal: Principal = Depends(require(Role.RESEARCHER)),
                         ctx: StoreContext = Depends(get_ctx),
                         services: AppServices = Depends(get_services)) -> Any:
    if body.object_id is not None:
        obj = ctx.repo.get_object(body.object_id)
        if obj is None:
            raise ApiError(404, "object_not_found", "object not found")
    else:  # resolve now so unknown/ambiguous targets fail fast with a precise error
        obj = services.make_resolver(ctx).resolve(body.query or "")
    params = {"object_id": str(obj.object_id), "mission": body.mission, "mode": body.mode,
              "segments": sorted(set(body.segments)), "max_observations": body.max_observations}
    key = job_key(obj.object_id, services.version_tag, params)
    job, created = JobStore(ctx.conn).create(str(uuid4()), "investigation", principal.name,
                                             params, key)
    audit(ctx, request, principal, "investigation.create", job.job_id,
          "accepted" if created else "deduplicated")
    if not created:
        return JSONResponse(JobOut(**_job_fields(job, True)).model_dump(mode="json"),
                            status_code=200)
    services.executor.submit(lambda: execute_job(services, job.job_id))
    return JobOut(**_job_fields(job))


@router.get("/investigations", response_model=list[JobOut], dependencies=READ)
def list_investigations(limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
                        principal: Principal = Depends(require(Role.VIEWER)),
                        ctx: StoreContext = Depends(get_ctx)) -> list[JobOut]:
    owner = None if principal.role == Role.ADMIN else principal.name
    return [JobOut(**_job_fields(j)) for j in JobStore(ctx.conn).list_for_owner(owner, limit,
                                                                                offset)]


@router.get("/investigations/{investigation_id}", response_model=InvestigationOut,
            dependencies=READ)
def get_investigation(investigation_id: UUID, principal: Principal = Depends(require(Role.VIEWER)),
                      ctx: StoreContext = Depends(get_ctx)) -> InvestigationOut:
    job = authorized_job(ctx, str(investigation_id), principal)
    out = InvestigationOut(**_job_fields(job), object_id=UUID(job.params["object_id"]))
    if job.status == SUCCEEDED:
        a = ctx.evidence.get_assessment(investigation_id)
        out.assessment = a.model_dump(mode="json") if a else None
        out.n_evidence = len(ctx.evidence.list_evidence(investigation_id))
    return out


@router.delete("/investigations/{investigation_id}", response_model=JobOut, status_code=202,
               dependencies=READ)
def cancel_investigation(investigation_id: UUID, request: Request,
                         principal: Principal = Depends(require(Role.RESEARCHER)),
                         ctx: StoreContext = Depends(get_ctx)) -> JobOut:
    job = authorized_job(ctx, str(investigation_id), principal)
    if job.terminal:
        raise ApiError(409, "already_finished", f"investigation already {job.status}")
    jobs = JobStore(ctx.conn)
    job = jobs.request_cancel(job.job_id) or job
    if job.status == QUEUED:  # not started yet: cancel immediately, the worker will see it
        jobs.finish(job.job_id, CANCELLED)
        jobs.append_event(job.job_id, "job_cancelled", {})
        job = jobs.get(job.job_id) or job
    audit(ctx, request, principal, "investigation.cancel", job.job_id, "requested")
    return JobOut(**_job_fields(job))


@router.get("/investigations/{investigation_id}/log", response_model=list[EventOut],
            dependencies=READ)
def event_log(investigation_id: UUID, after: int = Query(0, ge=0), limit: int = Query(500, ge=1,
                                                                                     le=1000),
              principal: Principal = Depends(require(Role.VIEWER)),
              ctx: StoreContext = Depends(get_ctx)) -> list[EventOut]:
    """Polling fallback for the SSE stream: the same events, after a given sequence number."""
    authorized_job(ctx, str(investigation_id), principal)
    return [EventOut(**e) for e in JobStore(ctx.conn).events_after(str(investigation_id), after,
                                                                   limit)]


def _sse(e: dict[str, Any]) -> str:
    payload = json.dumps(e["data"] | {"ts": e["ts"]})
    return f"id: {e['seq']}\nevent: {e['kind']}\ndata: {payload}\n\n"


@router.get("/investigations/{investigation_id}/events", dependencies=READ)
def stream_events(investigation_id: UUID, after: int = Query(0, ge=0),
                  last_event_id: str | None = Header(None),
                  principal: Principal = Depends(require(Role.VIEWER)),
                  ctx: StoreContext = Depends(get_ctx),
                  services: AppServices = Depends(get_services)) -> StreamingResponse:
    """Server-Sent Events. Resumable via Last-Event-ID (or ?after=). Ends after the terminal
    event. The generator opens its own connection: request-scoped ones close before streaming."""
    job_id = authorized_job(ctx, str(investigation_id), principal).job_id
    start = int(last_event_id) if last_event_id and last_event_id.isdigit() else after
    poll, limit = services.settings.api_sse_poll_interval_s, services.settings.api_sse_max_seconds

    def gen() -> Iterator[str]:
        last, t0, quiet_since = start, time.monotonic(), time.monotonic()
        with services.context() as c:
            jobs = JobStore(c.conn)
            while True:
                events = jobs.events_after(job_id, last)
                for e in events:
                    last = e["seq"]
                    quiet_since = time.monotonic()
                    yield _sse(e)
                    if e["kind"] in TERMINAL_EVENT_KINDS:
                        return
                job = jobs.get(job_id)
                if job is None or (job.terminal and not events):
                    yield "event: end\ndata: {}\n\n"
                    return
                if time.monotonic() - t0 > limit:
                    yield "event: timeout\ndata: {}\n\n"
                    return
                if time.monotonic() - quiet_since > 15:
                    quiet_since = time.monotonic()
                    yield ": keepalive\n\n"
                time.sleep(poll)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/investigations/{investigation_id}/evidence", dependencies=READ)
def evidence(investigation_id: UUID, principal: Principal = Depends(require(Role.VIEWER)),
             ctx: StoreContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    authorized_job(ctx, str(investigation_id), principal)
    return evidence_matrix(ctx.evidence.list_evidence(investigation_id), ctx.prov)


@router.get("/investigations/{investigation_id}/provenance", response_model=ProvenanceGraphOut,
            dependencies=READ)
def provenance(investigation_id: UUID, principal: Principal = Depends(require(Role.VIEWER)),
               ctx: StoreContext = Depends(get_ctx)) -> ProvenanceGraphOut:
    authorized_job(ctx, str(investigation_id), principal)
    ids = list(dict.fromkeys(p for e in ctx.evidence.list_evidence(investigation_id)
                             for p in e.provenance_ids))
    nodes, edges = ctx.prov.graph(ids)
    verifiable = True
    for pid in ids:
        try:
            ctx.prov.verify_chain(pid)
        except Exception:  # noqa: BLE001  (reported as a flag, never raised to the client)
            verifiable = False
            break
    return ProvenanceGraphOut(
        nodes=[ProvNode(prov_id=n.prov_id, entity_type=n.entity_type, activity=n.activity,
                        code_version=n.code_version, sha256=n.sha256, source_uri=n.source_uri,
                        dataset=n.dataset, release=n.release, at=n.at.isoformat()) for n in nodes],
        edges=[ProvEdge(from_prov=a, to_prov=b, relation=r) for a, b, r in edges],
        roots_verifiable=verifiable)
