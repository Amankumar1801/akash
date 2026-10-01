"""Live smoke tests against the real archives. Skipped by default.
Run:  uv run pytest -m network tests/live
They verify that our assumed field names / response shapes still match reality."""

import pytest
from akash_core.config import Settings
from akash_data.base import ObsFilter
from akash_data.factory import build_data_layer

pytestmark = pytest.mark.network


@pytest.fixture(scope="module")
def dl(tmp_path_factory):
    d = tmp_path_factory.mktemp("live")
    return build_data_layer(Settings(data_dir=str(d), sqlite_path=str(d / "m.sqlite3")))


def test_resolve_boyajian_star(dl):
    o = dl.resolver.resolve("KIC 8462852")
    assert o.alias("KIC") == "8462852"
    assert o.alias("GAIA_DR3") is not None


def test_exoplanet_archive_known_planet_host(dl):
    o = dl.resolver.resolve("Kepler-10")
    recs = dl.exoplanet_archive.lookup(o)
    assert any(r.status == "confirmed" for r in recs)


def test_kepler_lightcurve_ingest(dl):
    o = dl.resolver.resolve("KIC 8462852")
    res = dl.kepler.ingest(o, ObsFilter(max_observations=1))
    assert res.observations and not res.errors, (res.errors, res.quarantined)
    dl.prov.verify_chain(res.observations[0].provenance_id)
