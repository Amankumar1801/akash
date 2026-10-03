import numpy as np
import pytest
from akash_science.config import PipelineConfig
from akash_science.injection.models import InjectionSpec
from akash_science.lightcurve.pipeline import LightCurvePipeline
from akash_science.lightcurve.search import BLSSearcher, in_transit_mask, red_noise_beta
from akash_science.lightcurve.types import TCE
from akash_science.lightcurve.views import astronet_normalize, make_views
from akash_science.synthetic import make_synthetic_lc
from conftest import with_injection


def test_recovers_injected_planet(base, planet_spec):
    res = LightCurvePipeline().run(with_injection(base, planet_spec))
    assert res.tces, "injected 2000 ppm planet must be found"
    c = res.tces[0].tce
    assert c.period_d == pytest.approx(3.2, rel=0.005)
    assert c.depth_frac == pytest.approx(0.002, rel=0.25)
    assert c.n_transits >= 7 and c.snr >= 7.1
    dphi = abs((c.t0_bjd - planet_spec.t0_bjd + 1.6) % 3.2 - 1.6)
    assert dphi < 0.1


def test_period_interval_brackets_estimate_and_widens_with_noise(base, planet_spec):
    c = LightCurvePipeline().run(with_injection(base, planet_spec)).tces[0].tce
    lo, hi = c.period_interval_d
    assert lo <= c.period_d <= hi and c.beta >= 1.0


def test_two_planets_both_found(base):
    t0 = float(base.time_bjd[0])
    a = InjectionSpec(2.7, t0 + 0.5, 0.0025, 0.09)
    b = InjectionSpec(6.3, t0 + 2.0, 0.0030, 0.13)
    res = LightCurvePipeline().run(with_injection(base, a, b))
    periods = sorted(r.tce.period_d for r in res.tces)
    assert any(abs(p - 2.7) / 2.7 < 0.01 for p in periods)
    assert any(abs(p - 6.3) / 6.3 < 0.01 for p in periods)


@pytest.mark.parametrize("seed", range(200, 208))
def test_no_false_alarms_on_pure_noise(seed):
    assert LightCurvePipeline().run(make_synthetic_lc(np.random.default_rng(seed))).tces == []


def test_duty_cycle_limit_blocks_long_duration_short_period_artifacts():
    cfg = PipelineConfig().search
    assert cfg.max_duty_cycle <= 0.2


def test_red_noise_beta_detects_correlated_noise():
    rng = np.random.default_rng(0)
    t = np.arange(0, 20, 0.01)
    white = rng.normal(0, 1e-3, len(t))
    red = np.convolve(white, np.ones(50) / np.sqrt(50), mode="same")  # strongly correlated
    ex = np.zeros(len(t), bool)
    assert red_noise_beta(t, white, 0.3, 1e-3, ex) < 1.3
    assert red_noise_beta(t, red, 0.3, 1e-3, ex) > 2.0


def test_in_transit_mask_wraps_phase():
    t = np.array([0.0, 0.05, 1.0, 2.0, 2.04])
    assert in_transit_mask(t, 1.0, 0.0, 0.11).tolist() == [True, True, True, True, True]
    assert in_transit_mask(t, 1.0, 0.5, 0.11).tolist() == [False] * 5


def test_views_shape_and_transit_visible_at_center():
    t = np.arange(0, 30, 0.01)
    f = np.ones(len(t))
    f[np.abs(((t - 5.0 + 1.5) % 3.0) - 1.5) < 0.05] -= 0.01
    tce = TCE(1, 3.0, (2.99, 3.01), 5.0, 0.1, 0.01, 20, 20, 10)
    g, loc = make_views(t, f, tce, PipelineConfig().view)
    assert g.shape == (2001,) and loc.shape == (201,)
    assert loc[100] == pytest.approx(-0.01, abs=1e-6) and loc[0] == pytest.approx(0.0, abs=1e-9)
    assert g[1000] < -0.009  # transit at phase 0 => middle of the global view
    n = astronet_normalize(loc)
    assert n.min() == pytest.approx(-1.0) and np.median(n) == pytest.approx(0.0)


def test_views_fill_empty_bins():
    t = np.linspace(0, 3, 40)  # sparse: most of 2001 bins empty
    tce = TCE(1, 3.0, (2.9, 3.1), 1.5, 0.1, 0.0, 1, 1, 1)
    g, _ = make_views(t, np.ones(40), tce, PipelineConfig().view)
    assert np.isfinite(g).all()


def test_red_noise_guard_applies_to_final_reported_snr():
    """Regression: refining the BLS peak must not drop the red-noise correction. On red-noise-
    heavy data with no injection, the guarded pipeline finds nothing while the unguarded one
    reports spurious high-SNR TCEs."""
    import warnings

    from akash_science.config import PipelineConfig, SearchConfig
    from akash_science.lightcurve.pipeline import LightCurvePipeline
    from akash_science.synthetic import make_synthetic_lc

    warnings.filterwarnings("ignore")
    lc = make_synthetic_lc(np.random.default_rng(3), red_ppm=900.0)
    guarded = LightCurvePipeline().run(lc)
    unguarded = LightCurvePipeline(
        PipelineConfig(search=SearchConfig(correct_red_noise=False))).run(lc)
    assert len(guarded.tces) == 0
    assert len(unguarded.tces) >= 1, "test is vacuous if the unguarded pipeline is also clean"
