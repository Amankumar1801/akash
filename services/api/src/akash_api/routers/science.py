"""Spectrum analysis and stochastic-variability descriptors.

Both endpoints are deterministic computation over data the caller supplies or already owns.
Neither classifies an object. Outputs carry their caveats and the standing disclaimer.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import numpy as np
from akash_data.lightcurve import NormalizedLightCurve
from akash_science.agn import analyze_variability
from akash_science.spectra import InvalidSpectrum, analyze_spectrum
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from ..auth import Principal, Role
from ..db import StoreContext
from ..deps import audit, get_ctx, get_services, rate_limited, require
from ..errors import ApiError
from ..services import AppServices

router = APIRouter(prefix="/v1")
LIMITED = [Depends(rate_limited("general", "api_rate_per_min"))]
MAX_SPECTRUM_POINTS = 20_000       # keeps the JSON body under the global body limit
DISCLAIMER = "AKASH assists investigation; it does not independently establish discoveries."


class SpectrumRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wavelength_a: list[float] = Field(min_length=50, max_length=MAX_SPECTRUM_POINTS)
    flux: list[float | None] = Field(min_length=50, max_length=MAX_SPECTRUM_POINTS)
    flux_err: list[float | None] | None = Field(default=None, max_length=MAX_SPECTRUM_POINTS)
    label: str | None = Field(default=None, max_length=80)


@router.post("/spectra/analyze", dependencies=LIMITED)
def analyze_spectrum_route(body: SpectrumRequest, request: Request,
                           principal: Principal = Depends(require(Role.VIEWER)),
                           ctx: StoreContext = Depends(get_ctx),
                           services: AppServices = Depends(get_services)) -> dict[str, Any]:
    flux = np.array([np.nan if v is None else v for v in body.flux], dtype=np.float64)
    err = (None if body.flux_err is None
           else np.array([np.nan if v is None else v for v in body.flux_err], dtype=np.float64))
    try:
        result = analyze_spectrum(np.array(body.wavelength_a, dtype=np.float64), flux, err)
    except InvalidSpectrum as exc:
        audit(ctx, request, principal, "spectrum.analyze", None, "invalid")
        raise ApiError(422, "invalid_spectrum", str(exc)) from exc
    out = result.to_dict()
    out["label"] = body.label
    services.metrics.inc("spectra_analyzed_total", {"status": out["redshift"]["status"]})
    audit(ctx, request, principal, "spectrum.analyze", result.input_sha256[:16],
          out["redshift"]["status"])
    return out


@router.get("/observations/{obs_id}/variability", dependencies=LIMITED)
def observation_variability(obs_id: UUID, request: Request,
                            principal: Principal = Depends(require(Role.VIEWER)),
                            ctx: StoreContext = Depends(get_ctx)) -> dict[str, Any]:
    """Stochastic-variability descriptors from the stored light curve (flagged points dropped)."""
    obs = ctx.repo.get_observation(obs_id)
    if obs is None:
        raise ApiError(404, "not_found", "observation not found")
    sha = ctx.prov.get(obs.provenance_id).sha256
    if not sha or not ctx.artifacts.exists(sha):
        raise ApiError(404, "not_found", "observation data is not available")
    lc = NormalizedLightCurve.from_npz_bytes(ctx.artifacts.get(sha))
    keep = lc.native_quality == 0
    out = analyze_variability(lc.time_bjd[keep], lc.flux[keep], lc.flux_err[keep])
    out.update(obs_id=str(obs_id), provenance_id=str(obs.provenance_id), input_sha256=sha,
               n_quality_dropped=int((~keep).sum()), disclaimer=DISCLAIMER)
    audit(ctx, request, principal, "variability.analyze", str(obs_id), out["character"])
    return out
