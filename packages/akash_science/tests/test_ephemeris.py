import numpy as np
import pytest
from akash_data.lightcurve import NormalizedLightCurve
from akash_science.injection.models import InjectionSpec, inject
from akash_science.lightcurve.ephemeris import process_ephemeris, stitch_lightcurves
from akash_science.synthetic import make_synthetic_lc


def injected(seed=1, **kw):
    base = make_synthetic_lc(np.random.default_rng(seed), days=20.0, cadence_s=1200.0)
    spec = InjectionSpec(3.2, float(base.time_bjd[0]) + 1.1, kw.get("depth", 0.003), 0.11)
    f = inject(base.time_bjd, base.flux, spec)
    return NormalizedLightCurve(base.time_bjd, f, base.flux_err, base.sap_flux,
                                base.native_quality, base.meta), spec


def test_known_ephemeris_recovers_depth_and_snr():
    lc, s = injected()
    r = process_ephemeris(lc, s.period_d, s.t0_bjd, s.duration_d)
    assert r is not None
    assert r.tce.depth_frac == pytest.approx(0.003, rel=0.25)
    assert r.tce.snr > 9 and r.tce.n_transits >= 5
    assert len(r.global_view) == 2001 and len(r.local_view) == 201
    assert {v.name for v in r.vetting} >= {"odd_even", "secondary_eclipse", "transit_shape"}


def test_wrong_ephemeris_has_low_snr():
    lc, s = injected()
    r = process_ephemeris(lc, 3.2 * 1.37, s.t0_bjd + 0.9, s.duration_d)
    assert r is not None and r.tce.snr < 5


def test_too_little_data_returns_none():
    lc, s = injected()
    short = NormalizedLightCurve(lc.time_bjd[:60], lc.flux[:60], lc.flux_err[:60],
                                 lc.sap_flux[:60], lc.native_quality[:60], lc.meta)
    assert process_ephemeris(short, 3.2, s.t0_bjd, 0.1) is None


def test_stitch_removes_quarter_offsets_and_sorts():
    a, _ = injected(1)
    b = make_synthetic_lc(np.random.default_rng(2), days=20.0, cadence_s=1200.0,
                          t_start=float(a.time_bjd[-1]) + 5.0)
    b2 = NormalizedLightCurve(b.time_bjd, b.flux * 1.07, b.flux_err, b.sap_flux,
                              b.native_quality, b.meta)  # 7% offset like a quarter boundary
    s = stitch_lightcurves([b2, a])  # deliberately out of order
    assert (np.diff(s.time_bjd) >= 0).all()
    ma, mb = np.median(s.flux[s.time_bjd <= a.time_bjd[-1]]), np.median(s.flux[s.time_bjd > a.time_bjd[-1]])
    assert abs(ma - mb) < 0.01
    with pytest.raises(ValueError):
        stitch_lightcurves([])
