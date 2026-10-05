import numpy as np
import pytest
from akash_data.lightcurve import NormalizedLightCurve
from akash_science.lightcurve.variability import (
    FEATURE_NAMES,
    REP_LEN,
    UnusableLightCurve,
    assess_artifacts,
    extract_variability,
)
from akash_science.synthetic_anomaly import ARTIFACTS, INTERESTING, KINDS, make_lc, make_population


@pytest.fixture(scope="module")
def pop():
    counts = {"normal": 14, "dimming": 6, "flares": 6, "eclipsing": 6, "extreme_amp": 6,
              "unusual_period": 6, "artifact_step": 8, "artifact_flagged": 6}
    lcs, labels = make_population(counts, seed=21)
    return [extract_variability(x) for x in lcs], np.array(labels)


def feat(res, labels, kind, name):
    i = FEATURE_NAMES.index(name)
    return np.array([r.features[i] for r, lb in zip(res, labels, strict=True) if lb == kind])


def test_feature_vector_contract(pop):
    res, _ = pop
    for r in res:
        assert r.features.shape == (len(FEATURE_NAMES),) and np.isfinite(r.features).all()
        assert r.representation.shape == (REP_LEN,) and r.representation.dtype == np.float32
        assert abs(np.median(r.representation)) < 1e-6  # median-subtracted
        assert {"n_points", "baseline_d", "noise_1h_ppm", "unflagged_fraction"} <= r.quality.keys()
        assert {"step_ratio", "ramp_ratio", "flagged_fraction", "outlier_flag_overlap"} == r.artifact.keys()


def test_features_respond_to_the_physics_they_name(pop):
    res, lab = pop
    assert feat(res, lab, "flares", "n_flares").mean() > 3 * max(feat(res, lab, "normal", "n_flares").mean(), 0.3)
    # day-long dimmings are invisible to a 1-day filter; the slow-dip features must see them
    slow_n = feat(res, lab, "normal", "log10_deepest_slow_dip_ppm")
    for kind in ("dimming", "eclipsing"):
        det = feat(res, lab, kind, "log10_deepest_slow_dip_ppm") > np.percentile(slow_n, 95)
        assert det.mean() >= 0.8, (kind, det.mean())
    assert feat(res, lab, "extreme_amp", "log10_std_ppm").min() > np.median(feat(res, lab, "normal", "log10_std_ppm"))
    # short-period variability: Lomb-Scargle log10(period) well below the normal population's
    assert np.median(feat(res, lab, "unusual_period", "ls_log10_period")) < \
        np.percentile(feat(res, lab, "normal", "ls_log10_period"), 25)


def test_instrumental_artifacts_are_flagged(pop):
    res, lab = pop
    for kind in ARTIFACTS:
        hit = np.mean([assess_artifacts(r.artifact)[0] for r, lb in zip(res, lab, strict=True) if lb == kind])
        assert hit >= 0.75, (kind, hit)


def test_ordinary_stars_and_real_events_are_not_flagged_as_artifacts(pop):
    """The failure mode that matters: a real dip/eclipse next to a data gap must not look like an
    instrument step (an earlier metric flagged 33% of dimming stars)."""
    res, lab = pop
    for kind in ("normal", "flares", "extreme_amp", "unusual_period", "eclipsing", "dimming"):
        sel = [assess_artifacts(r.artifact)[0] for r, lb in zip(res, lab, strict=True) if lb == kind]
        assert np.mean(sel) <= 0.17, (kind, np.mean(sel))
    assert np.mean([assess_artifacts(r.artifact)[0] for r, lb in zip(res, lab, strict=True) if lb == "normal"]) == 0.0


def test_artifact_reasons_are_human_readable():
    ok, reasons = assess_artifacts({"step_ratio": 9.0, "ramp_ratio": 1.0, "flagged_fraction": 0.4,
                                    "outlier_flag_overlap": 0.0})
    assert ok and len(reasons) == 2 and any("data gap" in r for r in reasons)
    assert assess_artifacts({"step_ratio": 1.0, "ramp_ratio": 1.0, "flagged_fraction": 0.0,
                             "outlier_flag_overlap": 0.0}) == (False, [])
    ok, _ = assess_artifacts({"step_ratio": 2.0, "ramp_ratio": 1.0, "flagged_fraction": 0.0,
                              "outlier_flag_overlap": 0.0}, {"step_ratio": 1.5})
    assert ok  # reference-derived thresholds override the defaults


def test_extraction_is_deterministic():
    lc = make_lc("normal", np.random.default_rng(3))
    a, b = extract_variability(lc), extract_variability(lc)
    assert np.array_equal(a.features, b.features) and np.array_equal(a.representation, b.representation)


def test_too_little_data_is_refused_with_a_reason():
    lc = make_lc("normal", np.random.default_rng(3))
    short = NormalizedLightCurve(lc.time_bjd[:200], lc.flux[:200], lc.flux_err[:200],
                                 lc.sap_flux[:200], lc.native_quality[:200], lc.meta)
    with pytest.raises(UnusableLightCurve, match="too little"):
        extract_variability(short)
    with pytest.raises(UnusableLightCurve):
        extract_variability(NormalizedLightCurve(lc.time_bjd[:10], lc.flux[:10], lc.flux_err[:10],
                                                 lc.sap_flux[:10], lc.native_quality[:10], lc.meta))


def test_generator_contract():
    assert set(INTERESTING) | set(ARTIFACTS) | {"normal"} == set(KINDS)
    with pytest.raises(ValueError):
        make_lc("alien_megastructure", np.random.default_rng(0))
    lcs, labels = make_population({"normal": 2, "flares": 1}, 0)
    assert labels == ["normal", "normal", "flares"] and len(lcs) == 3


def test_short_period_residual_feature_isolates_fast_variables(pop):
    """Added after measurement: generic detectors missed fast variability because high residual
    power and short residual period each occur separately in ordinary stars. The conjunction
    feature must separate it."""
    res, lab = pop
    normal = feat(res, lab, "normal", "resid_short_period_power")
    hit = feat(res, lab, "unusual_period", "resid_short_period_power") > np.percentile(normal, 95)
    assert hit.mean() >= 0.8
