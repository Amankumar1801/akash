import numpy as np
import pytest
from akash_core.errors import ValidationFailure
from akash_data.lightcurve import KEPLER, TESS, NormalizedLightCurve, parse_lightcurve_fits
from akash_data.validation import validate_lightcurve
from conftest import make_fits


def test_parse_tess_converts_time_and_drops_nan_time():
    lc = parse_lightcurve_fits(make_fits(n=500, nan_time=3), TESS)
    assert len(lc.time_bjd) == 497
    assert lc.meta["rows_dropped_nonfinite_time"] == 3
    assert lc.time_bjd[0] > 2457000  # absolute BJD, not BTJD
    assert lc.flux.dtype == np.float64 and lc.flux.dtype.byteorder in ("=", "|")
    assert lc.meta["target_id"] == 261136679 and lc.meta["data_rel"] == "DR27"


def test_parse_kepler_reference_epoch():
    lc = parse_lightcurve_fits(make_fits("Kepler", cadence_s=1765.5, ident=8462852), KEPLER)
    assert 2454833 < lc.time_bjd[0] < 2460000 and lc.meta["mission"] == "Kepler"


def test_unsorted_time_is_sorted_on_parse():
    lc = parse_lightcurve_fits(make_fits(shuffle=True, nan_time=0), TESS)
    assert (np.diff(lc.time_bjd) > 0).all()


def test_quality_flags_preserved_untouched():
    lc = parse_lightcurve_fits(make_fits(quality_bad_frac=0.5, nan_time=0), TESS)
    assert (lc.native_quality == 1).sum() == 250


@pytest.mark.parametrize("kw,msg", [
    (dict(drop_key="SECTOR"), "missing primary header"),
    (dict(timesys="UTC"), "TIMESYS"),
])
def test_bad_headers_fail(kw, msg):
    with pytest.raises(ValidationFailure, match=msg):
        parse_lightcurve_fits(make_fits(**kw), TESS)


def test_not_fits():
    with pytest.raises(ValidationFailure):
        parse_lightcurve_fits(b"<html>error page</html>", TESS)


def test_npz_roundtrip_no_pickle():
    lc = parse_lightcurve_fits(make_fits(), TESS)
    back = NormalizedLightCurve.from_npz_bytes(lc.to_npz_bytes())
    assert np.array_equal(back.flux, lc.flux, equal_nan=True) and back.meta == lc.meta


def test_validation_ok_and_cadence_metric():
    r = validate_lightcurve(parse_lightcurve_fits(make_fits(), TESS))
    assert r.ok and r.metrics["median_cadence_s"] == pytest.approx(120.0, rel=1e-3)


def test_validation_too_few_points():
    r = validate_lightcurve(parse_lightcurve_fits(make_fits(n=50, nan_time=0), TESS))
    assert not r.ok and "too few" in r.errors[0]


def test_validation_flags_unusual_cadence_and_bad_quality():
    r = validate_lightcurve(parse_lightcurve_fits(
        make_fits(cadence_s=77.0, quality_bad_frac=0.9, nan_time=0), TESS))
    assert r.ok and any("cadence" in w for w in r.warnings) and any("unflagged" in w for w in r.warnings)


def test_kepler_quality_column_is_sap_quality():
    """Regression: real Kepler files name the bitmask SAP_QUALITY, not QUALITY (Kepler-10 b)."""
    lc = parse_lightcurve_fits(
        make_fits("Kepler", cadence_s=1765.5, ident=11904151, quality_bad_frac=0.5, nan_time=0),
        KEPLER)
    assert (lc.native_quality == 1).sum() == 250


def test_missing_quality_column_names_both_spellings():
    import io

    from astropy.io import fits
    hd = fits.open(io.BytesIO(make_fits("Kepler", cadence_s=1765.5)))
    cols = [c for c in hd[1].columns if c.name != "SAP_QUALITY"]
    tab = fits.BinTableHDU.from_columns(cols, header=hd[1].header)
    buf = io.BytesIO()
    fits.HDUList([hd[0], tab]).writeto(buf)
    with pytest.raises(ValidationFailure, match="SAP_QUALITY/QUALITY"):
        parse_lightcurve_fits(buf.getvalue(), KEPLER)


def test_tess_still_requires_quality():
    import io

    from astropy.io import fits
    hd = fits.open(io.BytesIO(make_fits()))
    cols = [c for c in hd[1].columns if c.name != "QUALITY"]
    tab = fits.BinTableHDU.from_columns(cols, header=hd[1].header)
    buf = io.BytesIO()
    fits.HDUList([hd[0], tab]).writeto(buf)
    with pytest.raises(ValidationFailure, match="missing table columns"):
        parse_lightcurve_fits(buf.getvalue(), TESS)
