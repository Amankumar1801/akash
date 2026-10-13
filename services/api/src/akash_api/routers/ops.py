from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from ..auth import ApiKeyStore, Principal, Role
from ..db import StoreContext
from ..deps import authorized_job, get_ctx, get_services, rate_limited, require
from ..jobs import JobStore
from ..services import AppServices

router = APIRouter(prefix="/v1")
READ = [Depends(rate_limited("general", "api_rate_per_min"))]


@router.get("/metrics", dependencies=READ, response_model=None)
def metrics(format: str = Query("json", pattern="^(json|prometheus)$"),
            _: Principal = Depends(require(Role.ADMIN)),
            services: AppServices = Depends(get_services)) -> Any:
    if format == "prometheus":
        return PlainTextResponse(services.metrics.prometheus(),
                                 media_type="text/plain; version=0.0.4")
    return services.metrics.snapshot()


@router.get("/investigations/{investigation_id}/trace", dependencies=READ)
def trace(investigation_id: UUID, principal: Principal = Depends(require(Role.VIEWER)),
          ctx: StoreContext = Depends(get_ctx)) -> dict[str, Any]:
    """One timeline for one investigation: the API requests that touched it (with request ids,
    matching the access log) and the job's own events, in time order."""
    job = authorized_job(ctx, str(investigation_id), principal)
    rid = str(investigation_id)
    reqs = [{"ts": r["ts"], "source": "request", "kind": r["action"], "outcome": r["outcome"],
             "request_id": r["request_id"]}
            for r in ApiKeyStore(ctx.conn).audit_for_resource(rid)]
    evs = [{"ts": e["ts"], "source": "job", "kind": e["kind"], "seq": e["seq"],
            "phase": e["data"].get("phase"), "status": e["data"].get("status")}
           for e in JobStore(ctx.conn).events_after(rid, 0, 500)]
    tl = sorted(reqs + evs, key=lambda x: float(x["ts"] or 0))
    return {"investigation_id": rid, "trace_id": rid, "status": job.status, "timeline": tl}
