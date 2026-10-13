from __future__ import annotations

from uuid import UUID

from akash_agent.guard import clean_text
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from ..auth import Principal, Role
from ..db import StoreContext
from ..deps import audit, authorized_job, get_ctx, rate_limited, require
from ..errors import ApiError
from ..jobs import SUCCEEDED
from ..research import LABELS, LabelStore, ReviewLabel

router = APIRouter(prefix="/v1")
READ = [Depends(rate_limited("general", "api_rate_per_min"))]
WRITE = [Depends(rate_limited("label", "api_label_rate_per_min"))]


class LabelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: ReviewLabel
    note: str | None = Field(default=None, max_length=500)


class LabelOut(BaseModel):
    label_id: int
    reviewer: str
    label: str
    note: str | None
    triage_category: str | None
    created_at: float


@router.post("/investigations/{investigation_id}/labels", status_code=201, response_model=LabelOut,
             dependencies=WRITE)
def add_label(investigation_id: UUID, body: LabelIn, request: Request,
              principal: Principal = Depends(require(Role.RESEARCHER)),
              ctx: StoreContext = Depends(get_ctx)) -> LabelOut:
    job = authorized_job(ctx, str(investigation_id), principal)
    if job.status != SUCCEEDED:
        raise ApiError(409, "not_finished", "only finished investigations can be reviewed")
    note = clean_text(body.note, 500).strip() if body.note else None
    store = LabelStore(ctx.conn)
    # The category the models/rules gave at review time is stored with the label, so a later
    # model can be compared with human judgement on the same cases.
    lid = store.add(str(investigation_id), principal.name, body.label, note or None, job.category)
    audit(ctx, request, principal, "label.add", str(investigation_id), body.label)
    return LabelOut(**next(r for r in store.for_investigation(str(investigation_id))
                           if r["label_id"] == lid))


@router.get("/investigations/{investigation_id}/labels", response_model=list[LabelOut],
            dependencies=READ)
def list_labels(investigation_id: UUID, principal: Principal = Depends(require(Role.VIEWER)),
                ctx: StoreContext = Depends(get_ctx)) -> list[LabelOut]:
    authorized_job(ctx, str(investigation_id), principal)
    return [LabelOut(**r) for r in LabelStore(ctx.conn).for_investigation(str(investigation_id))]


@router.get("/labels/export", dependencies=READ)
def export_labels(_: Principal = Depends(require(Role.ADMIN)),
                  ctx: StoreContext = Depends(get_ctx)) -> dict[str, object]:
    """Latest label per reviewer and investigation. This is the interface an active-learning loop
    reads. Nothing here retrains anything: that is a deliberate, reviewed step."""
    rows = LabelStore(ctx.conn).export_latest()
    return {"labels": list(LABELS), "n": len(rows), "rows": rows}
