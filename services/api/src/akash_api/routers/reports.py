from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from akash_report import Report, build_report, to_html, to_markdown
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from ..auth import Principal, Role
from ..db import StoreContext
from ..deps import audit, authorized_job, get_ctx, get_services, rate_limited, require
from ..errors import ApiError
from ..jobs import SUCCEEDED
from ..services import AppServices
from ..views import ApiInvestigationView

router = APIRouter(prefix="/v1")
LIMITED = [Depends(rate_limited("report", "api_report_rate_per_min"))]


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    investigation_id: UUID
    format: Literal["json", "markdown", "html"] = "json"


def _verifiable(ctx: StoreContext, view: ApiInvestigationView) -> bool | None:
    ids = list(dict.fromkeys(p for r in view.evidence() for p in r["provenance_ids"]))
    if not ids:
        return None
    for pid in ids:
        try:
            ctx.prov.verify_chain(UUID(pid))
        except Exception:  # noqa: BLE001  (reported as a flag, never raised to the client)
            return False
    return True


@router.post("/reports", response_model=Report, dependencies=LIMITED,
             responses={200: {"content": {"text/markdown": {}, "text/html": {}}}})
def create_report(body: ReportRequest, request: Request,
                  principal: Principal = Depends(require(Role.VIEWER)),
                  ctx: StoreContext = Depends(get_ctx),
                  services: AppServices = Depends(get_services)) -> Response | Report:
    job = authorized_job(ctx, str(body.investigation_id), principal)
    if job.status != SUCCEEDED:
        raise ApiError(409, "not_finished", "the investigation has not finished")
    obj = ctx.repo.get_object(UUID(job.params["object_id"]))
    if obj is None:
        raise ApiError(404, "object_not_found", "object not found")
    view = ApiInvestigationView(ctx, body.investigation_id)
    report = build_report(
        investigation_id=str(body.investigation_id), object_name=obj.canonical_name,
        object_info={"ra_deg": obj.ra_deg, "dec_deg": obj.dec_deg},
        assessment=view.assessment(), evidence=view.evidence(),
        prov_verifiable=_verifiable(ctx, view),
        pipeline_version=services.settings.pipeline_version,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"))
    services.metrics.inc("reports_total", {"format": body.format})
    audit(ctx, request, principal, "report.create", str(body.investigation_id),
          f"{body.format}:{report.content_sha256[:12]}")
    if body.format == "json":
        return report
    name = f"akash-report-{str(body.investigation_id)[:8]}"
    if body.format == "markdown":
        return Response(to_markdown(report), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}.md"'})
    return Response(
        to_html(report), media_type="text/html; charset=utf-8",
        headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
                                            "sandbox",
                 "Content-Disposition": f'attachment; filename="{name}.html"'})
