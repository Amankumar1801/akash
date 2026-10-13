from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from akash_eval import ExperimentConfig, ExperimentResult
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from ..auth import Principal, Role
from ..db import StoreContext
from ..deps import audit, get_ctx, get_services, rate_limited, require
from ..errors import ApiError
from ..research import Experiment, ExperimentStore
from ..services import AppServices
from ..worker import execute_experiment

router = APIRouter(prefix="/v1")
READ = [Depends(rate_limited("general", "api_rate_per_min"))]
RUN = [Depends(rate_limited("experiment", "api_experiment_rate_per_min"))]


class ExperimentOut(BaseModel):
    experiment_id: UUID
    status: str
    created_at: float
    started_at: float | None
    finished_at: float | None
    done: int
    total: int
    error: str | None
    cancel_requested: bool
    config: ExperimentConfig
    result: ExperimentResult | None = None


def _out(e: Experiment, with_result: bool) -> ExperimentOut:
    return ExperimentOut(
        experiment_id=UUID(e.experiment_id), status=e.status, created_at=e.created_at,
        started_at=e.started_at, finished_at=e.finished_at, done=e.done, total=e.total,
        error=e.error, cancel_requested=e.cancel_requested,
        config=ExperimentConfig.model_validate(e.config),
        result=ExperimentResult.model_validate(e.result) if with_result and e.result else None)


def _owned(ctx: StoreContext, eid: UUID, p: Principal) -> Experiment:
    """404 for other people's experiments (admins may read all), like investigations."""
    e = ExperimentStore(ctx.conn).get(str(eid))
    if e is None or (e.owner != p.name and not p.at_least(Role.ADMIN)):
        raise ApiError(404, "not_found", "experiment not found")
    return e


@router.post("/experiments", status_code=202, response_model=ExperimentOut, dependencies=RUN)
def create_experiment(body: ExperimentConfig, request: Request,
                      principal: Principal = Depends(require(Role.RESEARCHER)),
                      ctx: StoreContext = Depends(get_ctx),
                      services: AppServices = Depends(get_services)) -> ExperimentOut:
    store = ExperimentStore(ctx.conn)
    if store.active_count(principal.name) >= 1:
        raise ApiError(409, "experiment_in_progress",
                       "you already have an experiment running; wait for it or cancel it")
    e = store.create(str(uuid4()), principal.name, body.model_dump(), body.key(),
                     body.n_trials + body.n_controls)
    audit(ctx, request, principal, "experiment.create", e.experiment_id, f"n={body.n_trials}")
    services.experiment_executor.submit(lambda: execute_experiment(services, e.experiment_id))
    return _out(e, False)


@router.get("/experiments", response_model=list[ExperimentOut], dependencies=READ)
def list_experiments(limit: int = Query(20, ge=1, le=100),
                     principal: Principal = Depends(require(Role.VIEWER)),
                     ctx: StoreContext = Depends(get_ctx)) -> list[ExperimentOut]:
    owner = None if principal.at_least(Role.ADMIN) else principal.name
    return [_out(e, False) for e in ExperimentStore(ctx.conn).list_for_owner(owner, limit)]


@router.get("/experiments/{experiment_id}", response_model=ExperimentOut, dependencies=READ)
def get_experiment(experiment_id: UUID, principal: Principal = Depends(require(Role.VIEWER)),
                   ctx: StoreContext = Depends(get_ctx)) -> ExperimentOut:
    return _out(_owned(ctx, experiment_id, principal), True)


@router.delete("/experiments/{experiment_id}", response_model=ExperimentOut,
               status_code=202, dependencies=READ)
def cancel_experiment(experiment_id: UUID, request: Request,
                      principal: Principal = Depends(require(Role.RESEARCHER)),
                      ctx: StoreContext = Depends(get_ctx)) -> Any:
    e = _owned(ctx, experiment_id, principal)
    if e.terminal:
        raise ApiError(409, "already_finished", f"experiment already {e.status}")
    store = ExperimentStore(ctx.conn)
    store.request_cancel(e.experiment_id)
    if e.status == "queued":
        store.finish(e.experiment_id, "cancelled")
    audit(ctx, request, principal, "experiment.cancel", e.experiment_id, "requested")
    return _out(store.get(e.experiment_id), False)  # type: ignore[arg-type]
