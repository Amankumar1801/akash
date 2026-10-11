"""ASGI entrypoint (`uvicorn akash_api.main:app`). `create_app` stays importable from here.

`app` is a lazy proxy: importing this module has no side effects (no database, no directories,
no network); the production application is built on the first ASGI event (the lifespan startup)."""

from __future__ import annotations

from typing import Any

from akash_core.config import Settings
from starlette.types import Receive, Scope, Send

from .app import DISCLAIMER, create_app
from .services import build_default_services

__all__ = ["DISCLAIMER", "app", "create_app"]


class _LazyApp:
    def __init__(self) -> None:
        self._app: Any = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._app is None:
            settings = Settings()
            self._app = create_app(settings, build_default_services(settings))
        await self._app(scope, receive, send)


app = _LazyApp()
