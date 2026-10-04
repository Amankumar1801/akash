import numpy as np
import pytest
from akash_core.errors import ValidationFailure
from akash_data.lightcurve import NormalizedLightCurve
from akash_ml.transit.build import BKJD_OFFSET, TceRecord, build_dataset, load_kepler_dr25_csv
from akash_science.injection.models import InjectionSpec, inject
from akash_science.synthetic import make_synthetic_lc

CSV = """# comment line from the archive
kepid,tce_plnt_num,tce_period,tce_time0bk,tce_duration,av_training_set
10001,1,3.2,135.0,2.6,PC
10001,2,7.9,136.0,3.1,AFP
10002,1,2.5,135.5,2.0,NTP
10003,1,5.0,134.0,4.0,UNK
10004,1,,135.0,2.0,PC
"""


def test_kepler_csv_parsing(tmp_path):
    f = tmp_path / "t.csv"
    f.write_text(CSV)
    recs = load_kepler_dr25_csv(f)
    assert [r.tce_id for r in recs] == ["10001.01", "10001.02", "10002.01"]  # UNK + blank dropped
    assert [r.label for r in recs] == [1, 0, 0]
    assert recs[0].t0_bjd == pytest.approx(135.0 + BKJD_OFFSET)
    assert recs[0].duration_d == pytest.approx(2.6 / 24.0)  # hours -> days


def test_kepler_csv_missing_columns_fail_loudly(tmp_path):
    f = tmp_path / "t.csv"
    f.write_text("kepid,period\n1,2\n")
    with pytest.raises(ValidationFailure, match="missing columns"):
        load_kepler_dr25_csv(f)


def lcs_for(star):
    if star == 3:
        raise RuntimeError("archive down")
    rng = np.random.default_rng(star)
    out = []
    for q in range(2):  # two "quarters", with a flux offset like a real quarter boundary
        b = make_synthetic_lc(rng, days=15.0, cadence_s=1200.0, gap=None,
                              t_start=2458325.0 + q * 16.0)
        spec = InjectionSpec(3.2, 2458326.1, 0.004, 0.11)
        out.append(NormalizedLightCurve(b.time_bjd, inject(b.time_bjd, b.flux, spec) * (1 + 0.03 * q),
                                        b.flux_err, b.sap_flux, b.native_quality, b.meta))
    return out


def test_build_dataset_groups_by_star_and_reports_skips():
    recs = [TceRecord(1, "1.01", 1, 3.2, 2458326.1, 0.11),
            TceRecord(1, "1.02", 0, 9.1, 2458327.0, 0.15),
            TceRecord(2, "2.01", 1, 3.2, 2458326.1, 0.11),
            TceRecord(3, "3.01", 1, 3.2, 2458326.1, 0.11)]  # provider fails for star 3
    skipped: list = []
    ds = build_dataset(recs, lcs_for, skipped)
    assert sorted(ds.tce_ids.tolist()) == ["1.01", "1.02", "2.01"]
    assert [s[0] for s in skipped] == ["3.01"] and "archive down" in skipped[0][1]
    i = ds.tce_ids.tolist().index("1.01")
    assert ds.meta["snr"][i] > 15 and ds.global_views.shape[1] == 2001
    assert ds.meta["snr"][i] > ds.meta["snr"][ds.tce_ids.tolist().index("1.02")]


def test_build_dataset_with_nothing_processable_raises():
    with pytest.raises(ValidationFailure):
        build_dataset([TceRecord(3, "3.01", 1, 3.2, 2458326.1, 0.11)], lcs_for)


def test_lightcurve_getter_composes_resolve_ingest_load():
    from akash_ml.transit.build import lightcurve_getter
    calls = []
    lcs = lcs_for(1)

    def resolve(k):
        calls.append(("resolve", k))
        return f"obj{k}"

    getter = lightcurve_getter(resolve, lambda o: [0, 1], lambda obs: lcs[obs])
    assert getter(1) == lcs and calls == [("resolve", 1)]
    empty = lightcurve_getter(resolve, lambda o: [], lambda obs: lcs[0])
    with pytest.raises(ValidationFailure, match="no light curves"):
        empty(2)
