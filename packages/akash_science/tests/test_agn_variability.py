import numpy as np
import pytest
from akash_science.agn import analyze_variability


def drw(seed, tau, n=2000, dt=0.02083, sig=0.05, noise=0.002):
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = (
            x[i - 1] * np.exp(-dt / tau) + sig * np.sqrt(1 - np.exp(-2 * dt / tau)) * rng.normal()
        )
    return np.arange(n) * dt, 1 + x + rng.normal(0, noise, n), np.full(n, noise)


def test_white_noise_is_not_variability():
    rng = np.random.default_rng(1)
    t = np.arange(2000) * 0.02083
    r = analyze_variability(t, 1 + rng.normal(0, 0.004, 2000), np.full(2000, 0.004))
    assert (
        r["character"] == "no_significant_variability" and not r["excess_variance"]["significant"]
    )


def test_drw_timescale_is_recovered_when_the_baseline_allows():
    t, f, e = drw(2, tau=2.0)  # baseline about 42 days, about 20 tau
    r = analyze_variability(t, f, e)
    assert r["character"] == "stochastic_aperiodic"
    d = r["damped_random_walk"]
    assert d["tau_d_reliable"] and 1.0 < d["tau_d_days"] < 4.0
    assert d["sigma_frac"] == pytest.approx(0.05, rel=0.35)
    assert r["excess_variance"]["fvar"] == pytest.approx(0.05, rel=0.25)


def test_short_baseline_is_reported_as_unconstrained():
    t, f, e = drw(3, tau=30.0)  # tau comparable to the 42 day baseline
    d = analyze_variability(t, f, e)["damped_random_walk"]
    assert d is None or (d["tau_d_reliable"] is False and d["note"])


def test_red_noise_is_not_called_periodic():
    calls = [analyze_variability(*drw(s, tau=2.0))["character"] for s in range(12)]
    assert "periodic_like" not in calls


def test_a_sinusoid_is_periodic_like_with_the_right_period():
    rng = np.random.default_rng(3)
    t = np.arange(2000) * 0.02083
    f = 1 + 0.02 * np.sin(2 * np.pi * t / 3.0) + rng.normal(0, 0.004, 2000)
    r = analyze_variability(t, f, np.full(2000, 0.004))
    assert r["character"] == "periodic_like"
    assert r["periodicity"]["best_period_d"] == pytest.approx(3.0, rel=0.03)


def test_missing_errors_fall_back_and_say_so():
    t, f, _ = drw(4, tau=2.0)
    r = analyze_variability(t, f)
    assert r["error_source"] == "point_to_point" and r["character"] != "insufficient_data"


@pytest.mark.parametrize(
    "t,f,why",
    [
        (np.arange(10.0), np.ones(10), "at least"),
        (np.arange(100.0), -np.ones(100), "positive"),
    ],
)
def test_unusable_input_is_insufficient_not_a_crash(t, f, why):
    r = analyze_variability(t, f)
    assert r["character"] == "insufficient_data" and why in r["reason"]


def test_bad_types_and_shapes_are_insufficient():
    assert analyze_variability(["a"], [1])["character"] == "insufficient_data"
    assert analyze_variability(np.arange(100.0), np.ones(99))["character"] == "insufficient_data"


def test_nonfinite_points_are_dropped_and_deterministic():
    t, f, e = drw(5, tau=2.0)
    f2 = f.copy()
    f2[::50] = np.nan
    a, b = analyze_variability(t, f2, e), analyze_variability(t, f2, e)
    assert a == b and a["n_points"] == 2000 - 40
    assert "does not say what kind of object" in " ".join(a["caveats"])


def test_degenerate_time_axis_does_not_crash():
    t = np.arange(100.0) * 1e-6
    r = analyze_variability(t, 1.0 + (np.arange(100) % 2) * 0.01)
    assert r["character"] in {
        "insufficient_data",
        "no_significant_variability",
        "stochastic_aperiodic",
        "periodic_like",
    }
