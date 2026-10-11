from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from ..auth import Principal, Role
from ..deps import get_services, rate_limited, require
from ..errors import ApiError
from ..schemas import ModelOut
from ..services import AppServices

router = APIRouter(prefix="/v1")
READ = [Depends(rate_limited("general", "api_rate_per_min"))]
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_LISTED = 200


def _meta(d: Path) -> dict[str, Any] | None:
    try:
        return dict(json.loads((d / "metadata.json").read_text()))
    except (OSError, ValueError):
        return None


def _model_dir(services: AppServices, name: str, version: str) -> Path:
    """Reject anything that is not a plain registry name, then confirm containment anyway."""
    root = services.registry_root
    if root is None or not _SAFE.match(name) or not _SAFE.match(version):
        raise ApiError(404, "not_found", "model not found")
    d = (root / name / version).resolve()
    if not d.is_relative_to(root.resolve()) or not d.is_dir():
        raise ApiError(404, "not_found", "model not found")
    return d


@router.get("/models", response_model=list[ModelOut], dependencies=READ)
def list_models(_: Principal = Depends(require(Role.VIEWER)),
                services: AppServices = Depends(get_services)) -> list[ModelOut]:
    root = services.registry_root
    out: list[ModelOut] = []
    if root is None or not root.is_dir():
        return []
    for nd in sorted(p for p in root.iterdir() if p.is_dir() and _SAFE.match(p.name)):
        for vd in sorted(p for p in nd.iterdir() if p.is_dir() and _SAFE.match(p.name)):
            m = _meta(vd)
            if m is not None and len(out) < MAX_LISTED:
                out.append(ModelOut(name=nd.name, version=vd.name, created_at=m.get("created_at"),
                                    feature_version=m.get("feature_version"),
                                    data_hash=m.get("data_hash"), n=m.get("n")))
    return out


@router.get("/models/{name}/{version}", dependencies=READ)
def get_model(name: str, version: str, _: Principal = Depends(require(Role.VIEWER)),
              services: AppServices = Depends(get_services)) -> dict[str, Any]:
    d = _model_dir(services, name, version)
    meta = _meta(d)
    if meta is None:
        raise ApiError(404, "not_found", "model not found")
    card = d / "MODEL_CARD.md"
    return {"metadata": meta, "model_card": card.read_text() if card.is_file() else None}
