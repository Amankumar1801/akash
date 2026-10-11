"""Application factory. With no services configured the app still serves /v1/health and answers
every other route with a clean 503, so a misconfigured deployment fails loudly, not oddly."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from akash_core import __version__
from akash_core.config import Settings
from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import Principal, Role
from .deps import rate_limited, require
from .errors import install_error_handlers
from .jobs import JobStore
from .routers import investigations, models, objects
from .schemas import MeOut
from .security import SecurityMiddleware
from .services import AppServices

DISCLAIMER = (
    "AKASH assists investigation and does not independently establish scientific discoveries."
)


def create_app(settings: Settings | None = None, services: AppServices | None = None) -> FastAPI:
    settings = settings or (services.settings if services else Settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if services is not None:
            with services.context() as ctx:  # jobs orphaned by a crash can never finish
                JobStore(ctx.conn).recover_orphans()
        yield
        if services is not None:
            services.executor.shutdown(wait=False)

    app = FastAPI(title="AKASH", version=__version__, lifespan=lifespan,
                  docs_url="/docs" if settings.env == "dev" else None,
                  redoc_url=None, openapi_url="/openapi.json" if settings.env == "dev" else None)
    app.state.services = services
    if services is not None:
        services.ensure_schema()

    if settings.api_cors_origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=[o.strip() for o in settings.api_cors_origins.split(",")
                                           if o.strip()],
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-API-Key", "Last-Event-ID"])
    app.add_middleware(SecurityMiddleware, max_body_bytes=settings.api_max_body_bytes)
    install_error_handlers(app)

    health = APIRouter(prefix="/v1")

    @health.get("/health")
    def health_check() -> dict[str, str]:  # public: no auth, no data, no dependencies
        return {"status": "ok", "version": __version__,
                "pipeline_version": settings.pipeline_version, "env": settings.env,
                "disclaimer": DISCLAIMER}

    @health.get("/me", response_model=MeOut, dependencies=[
        Depends(rate_limited("general", "api_rate_per_min"))])
    def me(principal: Principal = Depends(require(Role.VIEWER))) -> MeOut:
        return MeOut(name=principal.name, role=principal.role.name.lower(),
                     key_id=principal.key_id)

    for r in (health, objects.router, investigations.router, models.router):
        app.include_router(r)
    return app
