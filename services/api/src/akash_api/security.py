"""Pure-ASGI middleware (safe with streaming responses): request id, body-size limit, security
headers, access log. The access log records method/path/status/latency/principal, never headers,
query strings or bodies, so credentials cannot leak into logs."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .metrics import Metrics

access_log = logging.getLogger("akash.access")
_RID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class BodyTooLarge(Exception):
    pass


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int = 1_000_000,
                 metrics: Metrics | None = None) -> None:
        self.app, self.max_body, self.metrics = app, max_body_bytes, metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        hdrs = {k.lower(): v for k, v in scope.get("headers", [])}
        rid = hdrs.get(b"x-request-id", b"").decode("latin-1")
        rid = rid if _RID.match(rid) else uuid.uuid4().hex  # never trust/echo arbitrary input
        state: dict[str, Any] = scope.setdefault("state", {})
        state["request_id"] = rid
        started, status, t0 = False, 0, time.perf_counter()
        too_large = swallow = False

        async def emit(message: Message) -> None:
            """Single exit to the client: adds the security headers to every response start."""
            nonlocal started, status
            if message["type"] == "http.response.start":
                started, status = True, message["status"]
                h = list(message.get("headers", []))
                names = {k.lower() for k, _ in h}
                h.append((b"x-request-id", rid.encode()))
                h.append((b"x-content-type-options", b"nosniff"))
                h.append((b"referrer-policy", b"no-referrer"))
                if b"cache-control" not in names:
                    h.append((b"cache-control", b"no-store"))
                message = {**message, "headers": h}
            await send(message)

        async def reject_413() -> None:
            body = json.dumps({"error": {"code": "payload_too_large",
                                         "message": "request body too large",
                                         "request_id": rid}}).encode()
            await emit({"type": "http.response.start", "status": 413, "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode())]})
            await emit({"type": "http.response.body", "body": body})

        async def send_wrapper(message: Message) -> None:
            nonlocal swallow
            if swallow:
                return
            if too_large and message["type"] == "http.response.start":
                # the framework swallowed our exception and answered 400/500: say 413 instead
                swallow = True
                await reject_413()
                return
            await emit(message)

        received = 0

        async def limited_receive() -> Message:
            nonlocal received, too_large
            msg = await receive()
            if msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > self.max_body:
                    too_large = True
                    raise BodyTooLarge
            return msg

        cl = hdrs.get(b"content-length", b"")
        try:
            if cl.isdigit() and int(cl) > self.max_body:
                await reject_413()
            else:
                await self.app(scope, limited_receive, send_wrapper)
        except BodyTooLarge:
            if not started:
                await reject_413()
        finally:
            if self.metrics is not None:
                route = getattr(scope.get("route"), "path", None) or "unmatched"
                dt = time.perf_counter() - t0
                self.metrics.inc("http_requests_total", {
                    "method": scope["method"], "route": route, "status": f"{status // 100}xx"})
                self.metrics.observe("http_request_seconds", dt, {"route": route})
            access_log.info(json.dumps({
                "request_id": rid, "method": scope["method"], "path": scope["path"],
                "status": status, "ms": round((time.perf_counter() - t0) * 1000, 1),
                "principal": state.get("principal")}))
