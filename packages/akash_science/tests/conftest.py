from __future__ import annotations

import warnings

import numpy as np
import pytest
from akash_data.lightcurve import NormalizedLightCurve
from akash_science.injection.models import InjectionSpec, inject
from akash_science.synthetic import make_synthetic_lc


@pytest.fixture(autouse=True)
def _quiet():
    warnings.filterwarnings("ignore", category=RuntimeWarning)


def with_injection(base: NormalizedLightCurve, *specs: InjectionSpec) -> NormalizedLightCurve:
    f = base.flux
    for s in specs:
        f = inject(base.time_bjd, f, s)
    return NormalizedLightCurve(base.time_bjd, f, base.flux_err, base.sap_flux,
                                base.native_quality, dict(base.meta))


@pytest.fixture
def base():
    return make_synthetic_lc(np.random.default_rng(1))


@pytest.fixture
def planet_spec(base):
    return InjectionSpec(3.2, float(base.time_bjd[0]) + 1.1, 0.002, 0.1)


import sqlite3  # noqa: E402

from akash_data.storage import LocalArtifactStore  # noqa: E402
from akash_provenance import SqliteProvenanceStore  # noqa: E402


@pytest.fixture
def _db():
    return sqlite3.connect(":memory:", check_same_thread=False)


@pytest.fixture
def prov(_db):
    return SqliteProvenanceStore(_db)


@pytest.fixture
def artifacts(_db, tmp_path):
    return LocalArtifactStore(tmp_path / "objs", _db)
