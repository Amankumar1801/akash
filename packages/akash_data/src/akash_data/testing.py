"""Record/replay HTTP transports so tests never hit archives, and fixtures can be refreshed
from the real services with scripts/record_fixtures.py."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import httpx


def request_key(req: httpx.Request) -> str:
    body = req.content.decode("utf-8", "replace") if req.content else ""
    return hashlib.sha256(f"{req.method} {req.url}\n{body}".encode()).hexdigest()[:24]


class RecordingTransport(httpx.BaseTransport):
    def __init__(self, directory: Path, inner: httpx.BaseTransport | None = None) -> None:
        self.dir, self.inner = Path(directory), inner or httpx.HTTPTransport()
        self.dir.mkdir(parents=True, exist_ok=True)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        resp = self.inner.handle_request(request)
        resp.read()
        rec = {
            "method": request.method, "url": str(request.url),
            "request_body": request.content.decode("utf-8", "replace") if request.content else "",
            "status": resp.status_code,
            "headers": {"content-type": resp.headers.get("content-type", "")},
            "body_b64": base64.b64encode(resp.content).decode(),
        }
        (self.dir / f"{request_key(request)}.json").write_text(json.dumps(rec, indent=1))
        return httpx.Response(resp.status_code, headers=resp.headers, content=resp.content)


class ReplayTransport(httpx.BaseTransport):
    def __init__(self, directory: Path) -> None:
        self.dir = Path(directory)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        f = self.dir / f"{request_key(request)}.json"
        if not f.exists():
            raise AssertionError(f"no recorded fixture for {request.method} {request.url}")
        rec = json.loads(f.read_text())
        return httpx.Response(
            rec["status"], headers=rec["headers"], content=base64.b64decode(rec["body_b64"])
        )
