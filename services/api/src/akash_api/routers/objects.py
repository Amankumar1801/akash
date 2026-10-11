from __future__ import annotations

from uuid import UUID

import numpy as np
from akash_core.schemas import AstronomicalObject, Observation
from akash_data.lightcurve import NormalizedLightCurve
from fastapi import APIRouter, Depends, Query

from ..auth import Principal, Role
from ..db import StoreContext
from ..deps import get_ctx, get_services, rate_limited, require
from ..downsample import minmax_indices
from ..errors import ApiError
from ..schemas import AliasOut, LightCurveDataOut, ObjectOut, ObjectSearchRequest, ObservationOut
from ..services import AppServices

router = APIRouter(prefix="/v1")
READ = [Depends(rate_limited("general", "api_rate_per_min"))]


def object_out(o: AstronomicalObject) -> ObjectOut:
    return ObjectOut(
        object_id=o.object_id, canonical_name=o.canonical_name, ra_deg=o.ra_deg, dec_deg=o.dec_deg,
        anchor_namespace=o.anchor_namespace,
        aliases=[AliasOut(namespace=a.namespace, identifier=a.identifier) for a in o.aliases])


def observation_out(o: Observation) -> ObservationOut:
    seg = o.mission_meta.get("segment")
    return ObservationOut(obs_id=o.obs_id, dataset=o.dataset, release=o.release,
                          native_obs_id=o.native_obs_id, modality=o.modality.value,
                          segment=int(seg) if isinstance(seg, (int, float)) else None,
                          retrieved_at=o.retrieved_at.isoformat())


@router.post("/objects/search", response_model=ObjectOut, dependencies=READ)
def search_object(body: ObjectSearchRequest, _: Principal = Depends(require(Role.VIEWER)),
                  ctx: StoreContext = Depends(get_ctx),
                  services: AppServices = Depends(get_services)) -> ObjectOut:
    return object_out(services.make_resolver(ctx).resolve(body.query))


@router.get("/objects/{object_id}", response_model=ObjectOut, dependencies=READ)
def get_object(object_id: UUID, _: Principal = Depends(require(Role.VIEWER)),
               ctx: StoreContext = Depends(get_ctx)) -> ObjectOut:
    obj = ctx.repo.get_object(object_id)
    if obj is None:
        raise ApiError(404, "not_found", "object not found")
    return object_out(obj)


@router.get("/objects/{object_id}/observations", response_model=list[ObservationOut],
            dependencies=READ)
def list_observations(object_id: UUID, modality: str | None = Query(None, max_length=32),
                      _: Principal = Depends(require(Role.VIEWER)),
                      ctx: StoreContext = Depends(get_ctx)) -> list[ObservationOut]:
    if ctx.repo.get_object(object_id) is None:
        raise ApiError(404, "not_found", "object not found")
    return [observation_out(o) for o in ctx.repo.list_observations(object_id, modality)]


@router.get("/observations/{obs_id}/data", response_model=LightCurveDataOut, dependencies=READ)
def observation_data(obs_id: UUID, max_points: int = Query(2000, ge=50, le=20000),
                     _: Principal = Depends(require(Role.VIEWER)),
                     ctx: StoreContext = Depends(get_ctx)) -> LightCurveDataOut:
    """Plot-ready arrays, flux normalised to its median, min/max-envelope downsampled."""
    obs = ctx.repo.get_observation(obs_id)
    if obs is None:
        raise ApiError(404, "not_found", "observation not found")
    sha = ctx.prov.get(obs.provenance_id).sha256
    if not sha or not ctx.artifacts.exists(sha):
        raise ApiError(404, "not_found", "observation data is not available")
    lc = NormalizedLightCurve.from_npz_bytes(ctx.artifacts.get(sha))
    good = np.isfinite(lc.flux)
    med = float(np.median(lc.flux[good])) if good.any() else 1.0
    flux = lc.flux / (med if med else 1.0)
    idx = minmax_indices(flux, max_points)
    return LightCurveDataOut(
        obs_id=obs_id, n_total=len(flux), n_returned=len(idx), downsampled=len(idx) < len(flux),
        time_bjd=[float(x) for x in lc.time_bjd[idx]],
        flux=[float(v) if np.isfinite(v) else None for v in flux[idx]],
        quality_flagged=[bool(q) for q in (lc.native_quality[idx] != 0)])
