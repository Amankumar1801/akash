"""FastAPI dependencies: services, per-request store context, authentication, authorization,
rate limiting. Order matters and is fixed: authenticate -> authorize -> rate limit."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from fastapi import Depends, Request

from .auth import ApiKeyStore, Principal, Role
from .db import StoreContext
from .errors import ApiError, request_id_of
from .jobs import Job, JobStore
from .services import AppServices


def get_services(request: Request) -> AppServices:
    services: AppServices | None = request.app.state.services
    if services is None:
        raise ApiError(503, "service_unavailable", "the service is not configured")
    return services


def get_ctx(services: AppServices = Depends(get_services)) -> Iterator[StoreContext]:
    with services.context() as ctx:
        yield ctx


def _presented_key(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip()
    return request.headers.get("x-api-key")


def authenticate(request: Request, ctx: StoreContext = Depends(get_ctx)) -> Principal:
    keys = ApiKeyStore(ctx.conn)
    principal = keys.verify(_presented_key(request))
    if principal is None:
        keys.audit(None, "auth", request.url.path, "denied:bad_credentials", request_id_of(request))
        raise ApiError(401, "unauthenticated", "missing or invalid API key",
                       headers={"WWW-Authenticate": "Bearer"})
    request.scope.setdefault("state", {})["principal"] = principal.name
    return principal


def require(role: Role) -> Callable[..., Principal]:
    def dep(request: Request, principal: Principal = Depends(authenticate),
            ctx: StoreContext = Depends(get_ctx)) -> Principal:
        if not principal.at_least(role):
            ApiKeyStore(ctx.conn).audit(principal.name, "authz", request.url.path,
                                        f"denied:needs_{role.name.lower()}", request_id_of(request))
            raise ApiError(403, "forbidden", f"this action requires the {role.name.lower()} role")
        return principal
    return dep


def rate_limited(bucket: str, limit_attr: str) -> Callable[..., None]:
    def dep(principal: Principal = Depends(authenticate),
            services: AppServices = Depends(get_services)) -> None:
        wait = services.limiter.check(principal.key_id, bucket,
                                      int(getattr(services.settings, limit_attr)))
        if wait is not None:
            raise ApiError(429, "rate_limited", "too many requests",
                           headers={"Retry-After": str(max(int(wait) + 1, 1))})
    return dep


def audit(ctx: StoreContext, request: Request, principal: Principal, action: str,
          resource: str | None, outcome: str) -> None:
    ApiKeyStore(ctx.conn).audit(principal.name, action, resource, outcome, request_id_of(request))


def authorized_job(ctx: StoreContext, job_id: str, principal: Principal) -> Job:
    """404 (not 403) for other people's jobs, so ids cannot be enumerated."""
    job = JobStore(ctx.conn).get(job_id)
    if job is None or (principal.role != Role.ADMIN and job.owner != principal.name):
        raise ApiError(404, "not_found", "investigation not found")
    return job
