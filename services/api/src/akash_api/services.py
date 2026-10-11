"""Service container: everything an endpoint or job needs, behind factories so tests can swap in
fakes and production can swap in Celery/Postgres without touching the routers."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from uuid import UUID

from akash_core.config import Settings
from akash_core.enums import ProvRelation
from akash_core.errors import ValidationFailure
from akash_core.schemas import AstronomicalObject, ProvenanceRecord
from akash_data.base import ObsFilter
from akash_data.lightcurve import NormalizedLightCurve
from akash_fusion.assembler import InvestigationDeps
from akash_fusion.stellar import StellarService
from akash_ml.anomaly.engine import AnomalyEngine
from akash_ml.anomaly.reference import ReferencePopulation
from akash_ml.registry import load_system
from akash_ml.training import TrainedSystem
from akash_science.lightcurve.ephemeris import stitch_lightcurves
from akash_science.lightcurve.pipeline import LightCurvePipeline

from .auth import ApiKeyStore
from .db import StoreContext, make_store_context
from .jobs import InProcessExecutor, JobExecutor, JobStore
from .ratelimit import RateLimiter


@dataclass
class LightCurveBundle:
    lc: NormalizedLightCurve
    prov_id: UUID
    n_observations: int
    warnings: list[str] = field(default_factory=list)


class ResolverLike(Protocol):
    def resolve(self, query: str) -> AstronomicalObject: ...


class LightCurveSource(Protocol):
    def fetch(self, obj: AstronomicalObject, mission: str, segments: list[int],
              max_observations: int) -> LightCurveBundle: ...


@dataclass
class AppServices:
    settings: Settings
    db_path: str
    artifacts_dir: str
    make_resolver: Callable[[StoreContext], ResolverLike]
    make_lightcurve_source: Callable[[StoreContext], LightCurveSource]
    make_investigation_deps: Callable[[StoreContext, str], InvestigationDeps]
    executor: JobExecutor
    version_tag: str = "dev"  # part of the idempotency key: new models => new results
    registry_root: Path | None = None
    limiter: RateLimiter = field(default_factory=RateLimiter)

    @contextmanager
    def context(self) -> Iterator[StoreContext]:
        ctx = make_store_context(self.db_path, self.artifacts_dir)
        try:
            yield ctx
        finally:
            ctx.close()

    def ensure_schema(self) -> None:
        with self.context() as ctx:  # constructing the stores creates their tables
            ApiKeyStore(ctx.conn)
            JobStore(ctx.conn)


class DataLayerLightCurveSource:
    """Real source: ingest (cached, validated, with provenance) -> stitch -> one provenance record
    deriving from every normalized observation, so the whole chain still reaches the fetches."""

    def __init__(self, ctx: StoreContext, kepler: object, tess: object, code_version: str) -> None:
        self.ctx, self._svc, self.code_version = ctx, {"kepler": kepler, "tess": tess}, code_version

    def fetch(self, obj: AstronomicalObject, mission: str, segments: list[int],
              max_observations: int) -> LightCurveBundle:
        svc = self._svc[mission]
        res = svc.ingest(obj, ObsFilter(segments=tuple(segments) or None,  # type: ignore[attr-defined]
                                        max_observations=max_observations))
        if not res.observations:
            raise ValidationFailure(
                f"no usable {mission} light curves for this object "
                f"({len(res.errors)} errors, {len(res.quarantined)} quarantined)")
        lcs = [NormalizedLightCurve.from_npz_bytes(
            self.ctx.artifacts.get(self.ctx.prov.get(o.provenance_id).sha256 or ""))
            for o in res.observations]
        rec = self.ctx.prov.add(ProvenanceRecord(
            entity_type="stitched_lightcurve", activity="stitch@1", code_version=self.code_version))
        for o in res.observations:
            self.ctx.prov.link(rec.prov_id, o.provenance_id, ProvRelation.WAS_DERIVED_FROM)
        warns = [f"{n}: {why}" for n, why in [*res.errors, *res.quarantined]]
        return LightCurveBundle(stitch_lightcurves(lcs), rec.prov_id, len(lcs), warns)


class _ModelCache:
    """Loads the classifier/reference once per process (CNN weights are not cheap)."""

    def __init__(self, settings: Settings) -> None:
        self.s, self._lock = settings, threading.Lock()
        self._system: TrainedSystem | None = None
        self._engine: AnomalyEngine | None = None
        self._loaded = False

    def get(self) -> tuple[TrainedSystem | None, AnomalyEngine | None]:
        with self._lock:
            if not self._loaded:
                if self.s.transit_model:
                    name, version = self.s.transit_model.split("/", 1)
                    self._system = load_system(Path(self.s.registry_root) / name / version)
                if self.s.anomaly_reference:
                    self._engine = AnomalyEngine(ReferencePopulation.load(self.s.anomaly_reference))
                self._loaded = True
            return self._system, self._engine


def build_default_services(settings: Settings) -> AppServices:
    """Production wiring: real archives, models from the registry, thread executor."""
    from akash_data.factory import build_data_layer

    models = _ModelCache(settings)
    tag = f"{settings.pipeline_version}|{settings.transit_model or '-'}|" \
          f"{settings.anomaly_reference or '-'}"

    def dl(ctx: StoreContext):  # type: ignore[no-untyped-def]
        return build_data_layer(settings, conn=ctx.conn)

    def deps(ctx: StoreContext, mode: str) -> InvestigationDeps:
        layer = dl(ctx)
        system, engine = models.get()
        full = mode == "deep"  # 'quick' = pipeline + classifier only (no archive round-trips)
        return InvestigationDeps(
            pipeline=LightCurvePipeline(), prov=ctx.prov, artifacts=ctx.artifacts,
            code_version=settings.pipeline_version, store=ctx.evidence, system=system,
            anomaly=engine if full else None,
            catalog=layer.exoplanet_archive if full else None,
            stellar=StellarService(layer.gaia) if full else None)

    def source(ctx: StoreContext) -> LightCurveSource:
        layer = dl(ctx)
        return DataLayerLightCurveSource(ctx, layer.kepler, layer.tess, settings.pipeline_version)

    return AppServices(
        settings=settings, db_path=settings.sqlite_path,
        artifacts_dir=str(Path(settings.data_dir) / "objects"),
        make_resolver=lambda ctx: dl(ctx).resolver, make_lightcurve_source=source,
        make_investigation_deps=deps, executor=InProcessExecutor(settings.api_max_concurrent_jobs),
        version_tag=tag, registry_root=Path(settings.registry_root))
