"""One error envelope for every failure: {"error": {"code", "message", "request_id", ...}}.
Messages are written for the client; stack traces and upstream details stay in the server log."""

from __future__ import annotations

import logging
from typing import Any

from akash_core.errors import (
    AmbiguousIdentity,
    CircuitOpen,
    ObjectNotFound,
    ProviderError,
    ValidationFailure,
)
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("akash.api")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, extra: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.extra, self.headers = extra or {}, headers or {}


def request_id_of(request: Request) -> str | None:
    state = request.scope.get("state") or {}
    rid = state.get("request_id")
    return str(rid) if rid else None


def envelope(request: Request, status: int, code: str, message: str,
             extra: dict[str, Any] | None = None, headers: dict[str, str] | None = None
             ) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "request_id": request_id_of(request),
                      **(extra or {})}}
    return JSONResponse(body, status_code=status, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(request: Request, e: ApiError) -> JSONResponse:
        return envelope(request, e.status, e.code, e.message, e.extra, e.headers)

    @app.exception_handler(AmbiguousIdentity)
    async def _amb(request: Request, e: AmbiguousIdentity) -> JSONResponse:
        return envelope(request, 409, "ambiguous_identity", str(e),
                        {"candidates": e.candidates[:20]})

    @app.exception_handler(ObjectNotFound)
    async def _nf(request: Request, e: ObjectNotFound) -> JSONResponse:
        return envelope(request, 404, "object_not_found", str(e))

    @app.exception_handler(ValidationFailure)
    async def _val(request: Request, e: ValidationFailure) -> JSONResponse:
        return envelope(request, 422, "validation_failed", str(e)[:300])

    @app.exception_handler(CircuitOpen)
    async def _circuit(request: Request, e: CircuitOpen) -> JSONResponse:
        log.warning("circuit open: %s", e)
        return envelope(request, 503, "upstream_unavailable",
                        "an upstream archive is temporarily unavailable; retry later",
                        headers={"Retry-After": "30"})

    @app.exception_handler(ProviderError)
    async def _prov(request: Request, e: ProviderError) -> JSONResponse:
        log.warning("upstream failure: %s", e)  # details stay server-side
        return envelope(request, 502, "upstream_error", "an upstream archive request failed")

    @app.exception_handler(RequestValidationError)
    async def _rv(request: Request, e: RequestValidationError) -> JSONResponse:
        # echo locations and messages only, never the submitted values
        problems = [{"loc": [str(x) for x in err["loc"]], "msg": err["msg"]}
                    for err in e.errors()[:20]]
        return envelope(request, 422, "invalid_request", "request validation failed",
                        {"problems": problems})

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, e: StarletteHTTPException) -> JSONResponse:
        codes = {404: "not_found", 405: "method_not_allowed"}
        return envelope(request, e.status_code, codes.get(e.status_code, "http_error"),
                        "resource not found" if e.status_code == 404 else "request not allowed")

    @app.exception_handler(Exception)
    async def _boom(request: Request, e: Exception) -> JSONResponse:
        log.exception("unhandled error on %s", request.url.path)
        return envelope(request, 500, "internal_error", "internal server error")
