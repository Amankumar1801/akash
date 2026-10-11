from __future__ import annotations

import importlib.util
import sys
import threading
import time
import uuid
import warnings
from pathlib import Path

import numpy as np
import pytest
from akash_api.app import create_app
from akash_api.auth import ApiKeyStore
from akash_api.db import StoreContext
from akash_api.jobs import InProcessExecutor
from akash_api.services import AppServices, LightCurveBundle
from akash_core.config import Settings
from akash_core.enums import Modality
from akash_core.errors import AmbiguousIdentity, ObjectNotFound, ProviderError, ValidationFailure
from akash_core.schemas import AstronomicalObject, ObjectAlias, Observation, ProvenanceRecord
from akash_data.lightcurve import NormalizedLightCurve
from akash_fusion.assembler import InvestigationDeps
from akash_fusion.stellar import StellarService
from akash_ml.training import TrainConfig, train_system
from akash_ml.transit.splits import SplitManifest
from akash_ml.transit.synthetic_set import make_synthetic_transit_dataset
from akash_science.lightcurve.pipeline import LightCurvePipeline
from fastapi.testclient import TestClient

# Reuse the fusion tests' light-curve generators and catalog/Gaia fakes. Loaded by FILE PATH under
# a distinct module name: both directories contain a module called "conftest".
_spec = importlib.util.spec_from_file_location(
    "akash_fusion_test_fixtures",
    Path(__file__).resolve().parents[3] / "packages/akash_fusion/tests/conftest.py")
fusion_fixtures = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["akash_fusion_test_fixtures"] = fusion_fixtures
_spec.loader.exec_module(fusion_fixtures)  # type: ignore[union-attr]

warnings.filterwarnings("ignore")
make_lc, planet = fusion_fixtures.make_lc, fusion_fixtures.planet
GATE = threading.Event()  # releases the blocking 'TIC 5' source


@pytest.fixture(scope="session")
def system():
    ds = make_synthetic_transit_dataset(250, seed=1)
    return train_system(ds, SplitManifest.build(ds.star_ids, "api-test"),
                        TrainConfig(run_cnn=False, bootstrap=20), "test")


class FakeResolver:
    def __init__(self, ctx: StoreContext) -> None:
        self.ctx = ctx

    def resolve(self, query: str) -> AstronomicalObject:
        q = query.strip()
        if q == "AMBIG":
            raise AmbiguousIdentity("2 objects match", ["star A", "star B"])
        if q == "BAD":
            raise ValidationFailure("unsupported identifier")
        if q == "DOWN":
            raise ProviderError("simbad.internal.example:443 refused the connection")
        if not q.startswith("TIC ") or not q[4:].isdigit():
            raise ObjectNotFound(f"no object found for {q!r}")
        n = int(q[4:])
        if (existing := self.ctx.repo.find_by_alias("TIC", str(n))) is not None:
            return existing
        obj = AstronomicalObject(
            ra_deg=301.5, dec_deg=44.4, canonical_name=f"TIC {n}", pm_ra_mas_yr=0.0,
            pm_dec_mas_yr=0.0, aliases=[ObjectAlias(namespace="TIC", identifier=str(n), source="t"),
                                        ObjectAlias(namespace="GAIA_DR3", identifier=str(700 + n),
                                                    source="t")])
        self.ctx.repo.save_object(obj)
        return obj


class FakeSource:
    """TIC 1 planet | 2 no signal | 3 ProviderError | 4 unexpected crash | 5 blocks on GATE |
    6 a second planet."""

    def __init__(self, ctx: StoreContext) -> None:
        self.ctx = ctx

    def fetch(self, obj, mission, segments, max_observations):  # type: ignore[no-untyped-def]
        n = int(obj.alias("TIC") or 0)
        if n == 3:
            raise ProviderError("archive down: https://mast.internal.example/secret-path")
        if n == 4:
            raise RuntimeError("boom: /etc/passwd leaked? password=hunter2")
        if n == 5:
            GATE.wait(30)
        seed = {1: 1, 2: 5, 5: 1, 6: 2}.get(n, 1)
        base = make_lc(seed)
        lc = make_lc(seed, planet(base)) if n in (1, 5, 6) else base
        prov = self.ctx.prov.add(ProvenanceRecord(
            entity_type="stitched_lightcurve", activity="fetch:fake", code_version="test",
            sha256="cd" * 32, source_uri="https://mast.stsci.edu/fake", dataset="TESS-SPOC",
            release="test"))
        return LightCurveBundle(lc, prov.prov_id, 1, [])


def deps_factory(system):  # type: ignore[no-untyped-def]
    def make(ctx: StoreContext, mode: str) -> InvestigationDeps:
        full = mode == "deep"
        return InvestigationDeps(
            LightCurvePipeline(), ctx.prov, ctx.artifacts, "test", ctx.evidence, system, None,
            fusion_fixtures.FakeCatalog() if full else None,
            StellarService(fusion_fixtures.FakeGaia()) if full else None)
    return make


@pytest.fixture
def settings(tmp_path):
    return Settings(env="test", sqlite_path=str(tmp_path / "akash.sqlite3"),
                    data_dir=str(tmp_path), api_sse_poll_interval_s=0.01,
                    api_rate_per_min=100000, api_investigation_rate_per_min=100000)


@pytest.fixture
def services(settings, tmp_path, system):
    GATE.clear()
    s = AppServices(
        settings=settings, db_path=settings.sqlite_path, artifacts_dir=str(tmp_path / "objs"),
        make_resolver=FakeResolver, make_lightcurve_source=FakeSource,
        make_investigation_deps=deps_factory(system), executor=InProcessExecutor(2),
        version_tag="test-v1", registry_root=tmp_path / "registry")
    yield s
    GATE.set()
    s.executor.shutdown(wait=True)


@pytest.fixture
def keys(services):
    services.ensure_schema()
    with services.context() as ctx:
        store = ApiKeyStore(ctx.conn)
        return {"viewer": store.create("vera", "viewer"), "researcher": store.create("rita", "researcher"),
                "researcher2": store.create("ron", "researcher"), "admin": store.create("ada", "admin")}


@pytest.fixture
def client(services, settings, keys):
    with TestClient(create_app(settings, services)) as c:
        yield c


def H(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def wait_done(client: TestClient, headers: dict[str, str], inv_id: str, timeout: float = 90.0
              ) -> dict:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        body = client.get(f"/v1/investigations/{inv_id}", headers=headers).json()
        if body["status"] in ("succeeded", "failed", "cancelled"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {inv_id} did not finish: {body}")


def submit(client, key, query="TIC 1", **kw):
    r = client.post("/v1/investigations", json={"query": query, **kw}, headers=H(key))
    return r


def add_observation(services: AppServices, obj: AstronomicalObject, lc: NormalizedLightCurve
                    ) -> uuid.UUID:
    """Store a normalized light curve exactly as the ingest pipeline would."""
    with services.context() as ctx:
        npz = ctx.artifacts.put(lc.to_npz_bytes(), "normalized_lightcurve")
        prov = ctx.prov.add(ProvenanceRecord(
            entity_type="normalized_lightcurve", activity="normalize:test", code_version="t",
            sha256=npz.sha256, source_uri="https://mast.stsci.edu/x", dataset="TESS-SPOC"))
        obs = Observation(object_id=obj.object_id, dataset="TESS-SPOC", native_obs_id="x_lc.fits",
                          modality=Modality.LIGHT_CURVE, mission_meta={"segment": 7},
                          artifact_ids=[npz.artifact_id], provenance_id=prov.prov_id)
        ctx.repo.save_observation(obs)
        return obs.obs_id
