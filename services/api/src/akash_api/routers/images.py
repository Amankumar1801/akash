"""Image analysis: morphology descriptors for one uploaded single-band image.

Input is either an uncompressed FITS file or raw float32 pixels (the browser converts PNG or JPEG to
grey pixels first). Sizes are bounded, nothing is stored, and no class label is returned."""

from __future__ import annotations

import base64
import binascii
from typing import Any

import numpy as np
from akash_science.imaging import (
    InvalidImage,
    analyze_image,
    downsample_for_preview,
    read_fits_bytes,
)
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from ..auth import Principal, Role
from ..db import StoreContext
from ..deps import audit, get_ctx, get_services, rate_limited, require
from ..errors import ApiError
from ..services import AppServices

router = APIRouter(prefix="/v1")
LIMITED = [Depends(rate_limited("general", "api_rate_per_min"))]
MAX_B64 = 900_000  # about 675 kB of raw bytes, inside the global body limit
MAX_SIDE = 512


class ImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fits_b64: str | None = Field(default=None, max_length=MAX_B64)
    pixels_b64: str | None = Field(default=None, max_length=MAX_B64)
    width: int | None = Field(default=None, ge=1, le=MAX_SIDE)
    height: int | None = Field(default=None, ge=1, le=MAX_SIDE)
    label: str | None = Field(default=None, max_length=80)


def _decode(s: str) -> bytes:
    try:
        return base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ApiError(422, "invalid_image", "the image data is not valid base64") from exc


@router.post("/images/analyze", dependencies=LIMITED)
def analyze_image_route(
    body: ImageRequest,
    request: Request,
    principal: Principal = Depends(require(Role.VIEWER)),
    ctx: StoreContext = Depends(get_ctx),
    services: AppServices = Depends(get_services),
) -> dict[str, Any]:
    has_fits = body.fits_b64 is not None
    has_pix = body.pixels_b64 is not None
    if has_fits == has_pix:
        raise ApiError(
            422, "invalid_image", "send either fits_b64 or pixels_b64, not both or neither"
        )
    try:
        if has_fits:
            data = read_fits_bytes(_decode(body.fits_b64 or ""))
            kind = "fits"
        else:
            if body.width is None or body.height is None:
                raise ApiError(422, "invalid_image", "pixels_b64 needs width and height")
            raw = _decode(body.pixels_b64 or "")
            if len(raw) != body.width * body.height * 4:
                raise ApiError(
                    422,
                    "invalid_image",
                    "pixels_b64 must hold width x height little-endian float32 values",
                )
            data = (
                np.frombuffer(raw, dtype="<f4").astype(np.float64).reshape(body.height, body.width)
            )
            kind = "pixels"
        result = analyze_image(data)
        preview = downsample_for_preview(data)
    except InvalidImage as exc:
        audit(ctx, request, principal, "image.analyze", None, "invalid")
        raise ApiError(422, "invalid_image", str(exc)) from exc
    out = result.to_dict()
    out.update(preview=preview, label=body.label, input_kind=kind)
    services.metrics.inc("images_analyzed_total", {"status": result.status})
    audit(ctx, request, principal, "image.analyze", result.input_sha256[:16], result.status)
    return out
