"""FastAPI entrypoint. Routers stay thin: no science or ML logic lives here."""

from akash_core import __version__
from akash_core.config import Settings
from fastapi import APIRouter, FastAPI

DISCLAIMER = (
    "AKASH assists investigation and does not independently establish scientific discoveries."
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="AKASH", version=__version__)
    router = APIRouter(prefix="/v1")

    @router.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "version": __version__,
            "pipeline_version": settings.pipeline_version,
            "env": settings.env,
            "disclaimer": DISCLAIMER,
        }

    app.include_router(router)
    return app


app = create_app()
