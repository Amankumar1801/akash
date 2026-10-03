import numpy as np
import pytest
from akash_core.enums import VetStatus
from akash_science.injection.models import InjectionSpec
from akash_science.lightcurve.pipeline import LightCurvePipeline
from akash_science.lightcurve.types import StellarContext, VetContext
from akash_science.lightcurve.vetting import (
    DepthRadiusCheck,
    DurationPlausibilityCheck,
    SystematicsCoincidenceCheck,
    run_checks,
)
from conftest import with_injection


def statuses(res):
    return {v.name: v.status for v in res.tces[0].vetting}


def test_clean_planet_has_no_fail(base, planet_spec):
    s = statuses(LightCurvePipeline().run(with_injection(base, planet_spec)))
    assert VetStatus.FAIL not in s.values()
    assert s["odd_even"] == VetStatus.PASS and s["secondary_eclipse"] == VetStatus.PASS
    assert s["transit_shape"] == VetStatus.PASS
    assert s["duration_plausibility"] == VetStatus.UNKNOWN  # no stellar info supplied


def test_eclipsing_binary_is_detected_and_flagged_by_vetting(base):
    """An EB (deep + shallow eclipse, true period 4 d) must be detected as a TCE, and vetting
    must flag it however the search locks on: at P=4 the shallow event is a secondary eclipse;
    at P=2 the alternating depths fail the odd/even test."""
    t0 = float(base.time_bjd[0]) + 1.0
    deep = InjectionSpec(4.0, t0, 0.004, 0.1)
    shallow = InjectionSpec(4.0, t0 + 2.0, 0.0015, 0.1)
    res = LightCurvePipeline().run(with_injection(base, deep, shallow))
    assert res.tces, "EB must be detected as a TCE; vetting is what should reject it"
    flagged = (VetStatus.FAIL, VetStatus.WARN)
    seen_check = {}
    for r in res.tces:
        s = {v.name: v.status for v in r.vetting}
        if abs(r.tce.period_d - 4.0) < 0.05:
            seen_check["P4"] = s["secondary_eclipse"]
            assert s["secondary_eclipse"] in flagged
        elif abs(r.tce.period_d - 2.0) < 0.05:
            seen_check["P2"] = s["odd_even"]
            assert s["odd_even"] in flagged
    assert seen_check, "expected a TCE at the true period or its half"


def test_secondary_eclipse_flagged(base):
    t0 = float(base.time_bjd[0]) + 1.0
    pri = InjectionSpec(3.0, t0, 0.003, 0.1)
    sec = InjectionSpec(3.0, t0 + 1.5, 0.002, 0.1)
    res = LightCurvePipeline().run(with_injection(base, pri, sec))
    assert res.tces
    # BLS may lock onto the half period (primary+secondary alternate); then odd/even rejects it.
    # Either route must flag the system -- what must never happen is a clean pass.
    s = statuses(res)
    assert s["odd_even"] in (VetStatus.WARN, VetStatus.FAIL) or \
        s["secondary_eclipse"] in (VetStatus.WARN, VetStatus.FAIL)


def test_v_shape_flagged(base):
    t0 = float(base.time_bjd[0]) + 1.0
    v_shape = InjectionSpec(3.0, t0, 0.003, 0.12, ingress_fraction=0.5)  # triangle
    res = LightCurvePipeline().run(with_injection(base, v_shape))
    assert res.tces
    v = next(v for v in res.tces[0].vetting if v.name == "transit_shape")
    assert v.status == VetStatus.WARN and v.metrics["best_ingress_fraction"] >= 0.4


def _ctx(res, stellar=None, flagged=None):
    r = res.tces[0]
    return VetContext(res.time, res.flux_detrended, res.sigma, r.tce, {}, 
                      np.array([] if flagged is None else flagged), res.segments, stellar)


def test_systematics_check_warns_when_transits_hit_flagged_cadences(base, planet_spec):
    res = LightCurvePipeline().run(with_injection(base, planet_spec))
    flagged = np.array(res.tces[0].tce.transit_times_bjd)  # a flag at every transit centre
    v = SystematicsCoincidenceCheck().run(_ctx(res, flagged=flagged))
    assert v.status == VetStatus.WARN and v.metrics["frac_overlap_flagged"] == 1.0


def test_duration_plausibility_with_stellar_context(base, planet_spec):
    res = LightCurvePipeline().run(with_injection(base, planet_spec))
    sun = StellarContext(radius_rsun=1.0, logg=4.438)
    assert sun.density_solar == pytest.approx(1.0)
    ok = DurationPlausibilityCheck().run(_ctx(res, sun))
    assert ok.status in (VetStatus.PASS, VetStatus.WARN) and "expected_hours" in ok.metrics
    dense = StellarContext(radius_rsun=0.1, logg=5.5)  # tiny dense star: expected T far shorter
    assert DurationPlausibilityCheck().run(_ctx(res, dense)).status == VetStatus.FAIL


def test_depth_radius_flags_stellar_size_companion(base):
    t0 = float(base.time_bjd[0]) + 1.0
    res = LightCurvePipeline().run(with_injection(base, InjectionSpec(3.0, t0, 0.05, 0.1)))
    big = DepthRadiusCheck().run(_ctx(res, StellarContext(radius_rsun=1.0, logg=4.4)))
    assert big.status == VetStatus.WARN and big.metrics["implied_radius_rjup"] > 2


def test_broken_check_degrades_to_unknown_not_crash(base, planet_spec):
    class Boom:
        name = "boom"

        def run(self, ctx):
            raise RuntimeError("kaput")

    res = LightCurvePipeline().run(with_injection(base, planet_spec))
    out = run_checks(_ctx(res), (Boom(),))
    assert out[0].status == VetStatus.UNKNOWN and "kaput" in out[0].summary


def test_flat_bottom_planet_not_flagged_v_even_with_ingress_variation(base):
    t0 = float(base.time_bjd[0]) + 1.0
    for f in (0.05, 0.1, 0.2):
        res = LightCurvePipeline().run(with_injection(base, InjectionSpec(3.0, t0, 0.003, 0.12, f)))
        v = next(v for v in res.tces[0].vetting if v.name == "transit_shape")
        assert v.status == VetStatus.PASS, (f, v.summary)
