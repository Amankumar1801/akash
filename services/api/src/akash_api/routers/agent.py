from __future__ import annotations

from typing import Any
from uuid import UUID

from akash_agent import ResearchAgent
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from ..auth import Principal, Role
from ..db import StoreContext
from ..deps import audit, authorized_job, get_ctx, get_services, rate_limited, require
from ..errors import ApiError
from ..jobs import SUCCEEDED
from ..services import AppServices
from ..views import ApiInvestigationView

router = APIRouter(prefix="/v1")
ASK = [Depends(rate_limited("agent", "api_agent_rate_per_min"))]


class AskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=500)


class StatementOut(BaseModel):
    text: str
    kind: str
    evidence_ids: list[str]


class AskOut(BaseModel):
    statements: list[StatementOut]
    mode: str
    verified: bool
    note: str | None
    retrieved_evidence_ids: list[str]
    trace: list[dict[str, Any]]
    disclaimer: str = ("AKASH assists investigation; it does not independently establish "
                       "discoveries.")


@router.post("/investigations/{investigation_id}/ask", response_model=AskOut, dependencies=ASK)
def ask(investigation_id: UUID, body: AskIn, request: Request,
        principal: Principal = Depends(require(Role.VIEWER)),
        ctx: StoreContext = Depends(get_ctx),
        services: AppServices = Depends(get_services)) -> AskOut:
    job = authorized_job(ctx, str(investigation_id), principal)
    if job.status != SUCCEEDED:
        raise ApiError(409, "not_finished", "the investigation has not finished")
    view = ApiInvestigationView(ctx, investigation_id)
    agent = ResearchAgent(services.make_llm_provider())
    res = agent.ask(body.question, view)
    audit(ctx, request, principal, "agent.ask", str(investigation_id),
          f"{res.mode}:{'fallback' if res.fallback_reason else 'ok'}")
    return AskOut(
        statements=[StatementOut(text=s.text, kind=s.kind, evidence_ids=s.evidence_ids)
                    for s in res.answer.statements],
        mode=res.mode, verified=res.verified,
        note=("A model answer could not be verified, so this answer is built directly from "
              "the evidence." if res.fallback_reason and res.mode == "deterministic"
              and res.fallback_reason != "no model configured" else None),
        retrieved_evidence_ids=res.retrieved_evidence_ids,
        trace=[{"kind": t.kind, **{k: v for k, v in t.detail.items() if k != "reason"}}
               for t in res.trace])
