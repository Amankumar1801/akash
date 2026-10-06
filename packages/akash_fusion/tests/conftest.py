from __future__ import annotations

import sqlite3
import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pytest
from akash_core.errors import ProviderError
from akash_core.schemas import AstronomicalObject, ObjectAlias, ProvenanceRecord
from akash_data.base import CatalogRecord
from akash_data.lightcurve import NormalizedLightCurve
from akash_data.storage import LocalArtifactStore
from akash_fusion.assembler import InvestigationDeps
from akash_fusion.stellar import StellarService
from akash_fusion.store import EvidenceStore
from akash_ml.training import TrainConfig, train_system
from akash_ml.transit.splits import SplitManifest
from akash_ml.transit.synthetic_set import make_synthetic_transit_dataset
from akash_provenance import SqliteProvenanceStore
from akash_science.injection.models import InjectionSpec, inject
from akash_science.lightcurve.pipeline import LightCurvePipeline
from akash_science.synthetic import make_synthetic_lc

warnings.filterwarnings("ignore")


@pytest.fixture(scope="session")
def system():
    ds = make_synthetic_transit_dataset(250, seed=1)
    man = SplitManifest.build(ds.star_ids, "fusion-test-v1")
    return train_system(ds, man, TrainConfig(run_cnn=False, bootstrap=20), "test")


@pytest.fixture
def db():
    return sqlite3.connect(":memory:", check_same_thread=False)


@pytest.fixture
def prov(db):
    return SqliteProvenanceStore(db)


@pytest.fixture
def artifacts(db, tmp_path):
    return LocalArtifactStore(tmp_path / "objs", db)


@pytest.fixture
def store(db):
    return EvidenceStore(db)


@pytest.fixture
def lc_prov(prov):
    return prov.add(ProvenanceRecord(
        entity_type="normalized_lightcurve", activity="fetch:synthetic", code_version="test",
        sha256="ab" * 32, source_uri="https://mast.stsci.edu/synthetic", dataset="TESS-SPOC",
        release="DR-test")).prov_id


@pytest.fixture
def obj():
    return AstronomicalObject(
        ra_deg=301.5, dec_deg=44.4, canonical_name="TIC 1", pm_ra_mas_yr=0.0, pm_dec_mas_yr=0.0,
        aliases=[ObjectAlias(namespace="TIC", identifier="1", source="test"),
                 ObjectAlias(namespace="GAIA_DR3", identifier="777", source="test")])


def make_lc(seed: int = 1, *specs: InjectionSpec) -> NormalizedLightCurve:
    base = make_synthetic_lc(np.random.default_rng(seed), days=20.0, cadence_s=1200.0,
                             gap=(9.0, 10.0))
    f = base.flux
    for s in specs:
        f = inject(base.time_bjd, f, s)
    return NormalizedLightCurve(base.time_bjd, f, base.flux_err, base.sap_flux,
                                base.native_quality, base.meta)


def planet(lc: NormalizedLightCurve, p: float = 3.2, depth: float = 0.004) -> InjectionSpec:
    return InjectionSpec(p, float(lc.time_bjd[0]) + 1.1, depth, 0.11)


@dataclass
class FakeCatalog:
    records: list[CatalogRecord] = field(default_factory=list)
    fail: bool = False
    name: str = "exoplanet_archive"
    url: str = "https://exoplanetarchive.test/TAP"
    last_queries: list[str] = field(default_factory=list)

    def lookup(self, obj: AstronomicalObject) -> list[CatalogRecord]:
        self.last_queries = ["select ... from toi where tid = 1"]
        if self.fail:
            raise ProviderError("archive down")
        return self.records


def toi(period: float, disp: str = "CP", native: str = "100.01") -> CatalogRecord:
    status = {"CP": "confirmed", "PC": "candidate", "FP": "false_positive"}[disp]
    return CatalogRecord("NASA Exoplanet Archive", "toi", native,
                         {"tid": 1, "toi": native, "tfopwg_disp": disp, "pl_orbper": period},
                         status, "select * from toi where tid = 1", "https://exoplanetarchive.test/TAP")


@dataclass
class FakeGaia:
    star: dict[str, Any] = field(default_factory=lambda: {
        "source_id": 777, "phot_g_mean_mag": 12.0, "teff_gspphot": 5700.0,
        "logg_gspphot": 4.4, "radius_gspphot": 1.0, "ruwe": 1.0})
    neighbors: list[dict[str, Any]] = field(default_factory=list)
    url: str = "https://gaia.test/tap"
    last_query: str = ""

    def lookup(self, obj: AstronomicalObject) -> list[CatalogRecord]:
        self.last_query = "select ... where source_id = 777"
        return [CatalogRecord("Gaia", "gaiadr3.gaia_source", "777", dict(self.star), None,
                              self.last_query, self.url)]

    def cone_for_object_epoch(self, ra, dec, pmra, pmdec, epoch, radius):
        self.last_query = f"select top 20 ... cone r={radius}"
        rows = [dict(self.star, _sep_arcsec=0.1)] + [dict(n) for n in self.neighbors]
        return rows, (ra, dec)


def neighbor(sid: int, sep: float, g: float | None) -> dict[str, Any]:
    return {"source_id": sid, "_sep_arcsec": sep, "phot_g_mean_mag": g}


@pytest.fixture
def deps(prov, artifacts, store, system):
    return InvestigationDeps(
        pipeline=LightCurvePipeline(), prov=prov, artifacts=artifacts, code_version="test",
        store=store, system=system, catalog=FakeCatalog(), stellar=StellarService(FakeGaia()))
