import json

import numpy as np
import pytest
from akash_core.enums import QualityGrade
from akash_core.schemas import Anomaly
from akash_data.lightcurve import NormalizedLightCurve
from akash_ml.anomaly.autoencoder import Autoencoder
from akash_ml.anomaly.categorize import categorize
from akash_ml.anomaly.engine import AnomalyEngine, AnomalyStatus
from akash_ml.anomaly.evaluate import (
    evaluate_recovery,
    rank_stability,
    select_aggregator,
    tpr_at_fpr,
)
from akash_ml.anomaly.reference import ReferencePopulation, aggregate_scores
from akash_ml.uncertainty.quality import grade_lightcurve_quality
from akash_science.lightcurve.variability import REP_LEN, extract_variability
from akash_science.synthetic_anomaly import ARTIFACTS, INTERESTING, make_lc, make_population

KINDS = {"normal": 40, "dimming": 8, "flares": 8, "extreme_amp": 8, "unusual_period": 8,
         "eclipsing": 8, "artifact_step": 8, "artifact_flagged": 8}


@pytest.fixture(scope="module")
def ref_vrs():
    lcs, _ = make_population({"normal": 220}, seed=100)
    return [extract_variability(x) for x in lcs]


@pytest.fixture(scope="module")
def reference(ref_vrs):
    return ReferencePopulation("synthetic-normal-test", {"kind": "synthetic"}, seed=0).fit(
        ref_vrs, np.arange(len(ref_vrs)))


@pytest.fixture(scope="module")
def evalset():
    lcs, labels = make_population(KINDS, seed=700)
    return [extract_variability(x) for x in lcs], labels


@pytest.fixture(scope="module")
def results(reference, evalset):
    vrs, _ = evalset
    eng = AnomalyEngine(reference)
    return [eng.analyze_extracted(v) for v in vrs]


# ---------- autoencoder ----------
def test_autoencoder_reconstructs_normals_better_than_anomalies(ref_vrs, evalset):
    reps = np.stack([v.representation for v in ref_vrs])
    ae = Autoencoder(0).fit(reps[:160], reps[160:], epochs=40)
    vrs, labels = evalset
    err = ae.recon_error(np.stack([v.representation for v in vrs]))
    lab = np.array(labels)
    assert np.median(err[lab == "dimming"]) > 2 * np.median(err[lab == "normal"])
    assert ae.recon_residual(reps[:3]).shape == (3, REP_LEN) and ae.embed(reps[:3]).shape == (3, 8)


def test_autoencoder_deterministic_and_roundtrips(ref_vrs):
    reps = np.stack([v.representation for v in ref_vrs])[:80]
    a = Autoencoder(1).fit(reps[:60], reps[60:], epochs=5)
    b = Autoencoder(1).fit(reps[:60], reps[60:], epochs=5)
    assert np.allclose(a.recon_error(reps), b.recon_error(reps), atol=1e-6)
    back = Autoencoder.from_bytes(a.to_bytes())
    assert np.allclose(back.recon_error(reps), a.recon_error(reps), atol=1e-6)
    with pytest.raises(AssertionError):
        Autoencoder().recon_error(reps)


# ---------- reference population ----------
def test_aggregation_rules():
    m = np.array([[10.0, 90.0], [20.0, 95.0], [30.0, 10.0], [40.0, 20.0]])
    assert np.allclose(aggregate_scores(m, "mean"), [25.0, 53.75])
    assert np.allclose(aggregate_scores(m, "max"), [40.0, 95.0])
    assert np.allclose(aggregate_scores(m, "top2"), [35.0, 92.5])
    with pytest.raises(ValueError):
        aggregate_scores(m, "median")


def test_reference_needs_enough_rows(ref_vrs):
    with pytest.raises(ValueError, match="too small"):
        ReferencePopulation("tiny", {}).fit(ref_vrs[:20], np.arange(20))


def test_held_out_percentiles_are_roughly_uniform_on_new_normals(reference):
    """Percentiles are calibrated on held-out reference stars, so fresh normals should spread
    across 0-100 (an in-sample reference would pile up near the bottom)."""
    lcs, _ = make_population({"normal": 80}, seed=555)
    vrs = [extract_variability(x) for x in lcs]
    s = reference.score(np.stack([v.features for v in vrs]), np.stack([v.representation for v in vrs]))
    assert 35 < np.median(s.percentile) < 65
    assert np.mean(s.percentile > 90) < 0.2


def test_scores_are_scored_per_detector_and_visible(reference, evalset):
    vrs, _ = evalset
    s = reference.score(vrs[0].features, vrs[0].representation)
    assert set(s.percentiles) == {"iforest", "lof", "ae_recon", "latent_knn"}
    assert s.severity.shape == (1,) and 0 <= s.percentile[0] <= 100


def test_set_aggregate_changes_scoring_without_refit(reference, evalset):
    vrs, labels = evalset
    i = labels.index("extreme_amp")
    x, r = vrs[i].features, vrs[i].representation
    try:
        reference.set_aggregate("mean")
        mean_sev = reference.score(x, r).severity[0]
        reference.set_aggregate("max")
        max_sev = reference.score(x, r).severity[0]
    finally:
        reference.set_aggregate("top2")
    assert max_sev > mean_sev  # the autoencoder cannot see amplitude: `mean` dilutes it


def test_driver_z_uses_std_fallback_for_zero_inflated_features(reference):
    """Dip/flare counts are mostly 0 in the reference (MAD=0). They must fall back to the std and
    not be floored at scale 1, or amplitude features out-vote them (an earlier bug skewed every
    category toward 'high_amplitude_variability')."""
    x = reference.features
    raw_mad = 1.4826 * np.median(np.abs(x - np.median(x, axis=0)), axis=0)
    zero_inflated = np.where((raw_mad <= 1e-9) & (x.std(axis=0) > 1e-9))[0]
    assert len(zero_inflated) >= 2, "fixture should contain zero-inflated features"
    for i in zero_inflated:
        assert reference.mad[i] == pytest.approx(x[:, i].std())
    normal_cols = np.where(raw_mad > 1e-9)[0]
    assert np.allclose(reference.mad[normal_cols], raw_mad[normal_cols])


def test_reference_persistence_reproduces_scores(reference, evalset, tmp_path):
    vrs, _ = evalset
    reference.save(str(tmp_path / "ref"))
    back = ReferencePopulation.load(str(tmp_path / "ref"))
    f, r = np.stack([v.features for v in vrs[:20]]), np.stack([v.representation for v in vrs[:20]])
    a, b = reference.score(f, r), back.score(f, r)
    assert np.allclose(a.severity, b.severity, atol=1e-6) and np.allclose(a.percentile, b.percentile)
    meta = json.loads((tmp_path / "ref" / "meta.json").read_text())
    assert meta["ref_id"] == "synthetic-normal-test" and meta["fingerprint"] == back.fingerprint()


def test_reference_load_refuses_tampered_scores(reference, tmp_path):
    reference.save(str(tmp_path / "ref"))
    mp = tmp_path / "ref" / "meta.json"
    meta = json.loads(mp.read_text())
    meta["fingerprint"] = "0" * 64
    mp.write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="does not reproduce"):
        ReferencePopulation.load(str(tmp_path / "ref"))


# ---------- categorize ----------
@pytest.mark.parametrize("drivers,expected", [
    ([("n_flares", 8), ("log10_max_flare_ppm", 6), ("kurtosis", 9)], "flare_dominated"),
    ([("n_slow_dips", 7), ("log10_deepest_slow_dip_ppm", 5)], "unusual_dips"),
    ([("resid_short_period_power", 9), ("ls_log10_period", 4)], "unusual_periodicity"),
    ([("log10_std_ppm", 8), ("log10_range_ppm", 7)], "high_amplitude_variability"),
    ([("n_flares", 5), ("n_dips", 5), ("log10_std_ppm", 5), ("ls_peak_power", 5)], "feature_combination_outlier"),
    ([("skew", 9), ("kurtosis", 9)], "feature_combination_outlier"),  # shape moments cast no vote
    ([("resid_skew", -6), ("log10_deepest_dip_ppm", 3)], "unusual_dips"),
    ([("resid_skew", 6), ("n_flares", 3)], "flare_dominated"),
    ([], "feature_combination_outlier")])
def test_categorize(drivers, expected):
    assert categorize(drivers) == expected


# ---------- quality gate ----------
@pytest.mark.parametrize("q,grade", [
    (dict(n_points=1500, baseline_d=20, unflagged_fraction=0.99, beta=1.2), QualityGrade.A),
    (dict(n_points=700, baseline_d=12, unflagged_fraction=0.8, beta=1.2), QualityGrade.B),
    (dict(n_points=350, baseline_d=6, unflagged_fraction=0.6, beta=1.2), QualityGrade.C),
    (dict(n_points=200, baseline_d=3, unflagged_fraction=0.9, beta=1.2), QualityGrade.D),
    (dict(n_points=1500, baseline_d=20, unflagged_fraction=0.99, beta=4.0), QualityGrade.B)])
def test_lightcurve_quality_grades(q, grade):
    assert grade_lightcurve_quality({**q, "noise_1h_ppm": 500.0}).grade == grade


# ---------- engine ----------
def test_unusable_lightcurve_is_not_scored(reference):
    lc = make_lc("normal", np.random.default_rng(1))
    short = NormalizedLightCurve(lc.time_bjd[:200], lc.flux[:200], lc.flux_err[:200],
                                 lc.sap_flux[:200], lc.native_quality[:200], lc.meta)
    r = AnomalyEngine(reference).analyze(short)
    assert r.status == AnomalyStatus.INSUFFICIENT_DATA and r.percentile is None
    assert r.review_priority is None and r.to_core() is None
    assert r.data_quality.grade == QualityGrade.D and r.interpretation().startswith("Not scored")


def test_engine_wording_never_claims_a_discovery(results):
    for r in results:
        text = r.interpretation().lower()
        assert "not a discovery claim" in text or text.startswith("not scored")
        for banned in ("new planet", "confirmed", "proves", "we discovered"):
            assert banned not in text


def test_artifacts_are_scored_but_excluded_from_review(results, evalset):
    _, labels = evalset
    arts = [r for r, lb in zip(results, labels, strict=True) if lb in ARTIFACTS]
    flagged = [r for r in arts if r.status == AnomalyStatus.ARTIFACT_SUSPECT]
    assert len(flagged) / len(arts) >= 0.9
    for r in flagged:
        assert r.review_priority is None and r.percentile is not None
        assert r.category == "artifact_suspect" and r.artifact_reasons


def test_result_bridges_to_core_anomaly_schema(results, evalset):
    _, labels = evalset
    r = next(r for r, lb in zip(results, labels, strict=True)
             if lb == "flares" and r.status == AnomalyStatus.SCORED)
    core = r.to_core()
    assert isinstance(core, Anomaly) and core.reference_population == "synthetic-normal-test"
    assert 0 <= core.percentile <= 100 and len(core.drivers) == 5
    assert r.unusual_regions and all(0 <= a <= b <= 1 for a, b, _ in r.unusual_regions)


def test_interesting_objects_rank_above_normals(results, evalset):
    _, labels = evalset
    m = evaluate_recovery(results, labels)
    assert m["auroc_interesting_vs_normal"] >= 0.9
    assert m["artifact_flag_rate_artifacts"] >= 0.9
    assert m["false_artifact_flag_rate_normal"] <= 0.1
    assert m["false_artifact_flag_rate_interesting"] <= 0.25
    for t in m["top_k"].values():  # the gate may only help
        assert t["artifact_rate_gated"] <= t["artifact_rate_ungated"] + 1e-9
    assert m["top_k"]["10%"]["precision_interesting_gated"] >= 0.9


def test_per_kind_detection_has_no_blind_spots_at_fixed_fpr(results, evalset):
    _, labels = evalset
    m = evaluate_recovery(results, labels)
    for kind in INTERESTING:
        assert m["per_kind"][kind]["tpr_at_5pct_fpr"] >= 0.6, (kind, m["per_kind"][kind])
    assert m["category_agreement"]["flares"] >= 0.7 and m["category_agreement"]["eclipsing"] >= 0.7


def test_stability_across_seeds(ref_vrs, evalset, results):
    vrs, _ = evalset
    other = ReferencePopulation("synthetic-normal-test", {}, seed=7).fit(ref_vrs, np.arange(len(ref_vrs)))
    eng = AnomalyEngine(other)
    b = [eng.analyze_extracted(v) for v in vrs]
    sev = lambda rs: np.array([r.severity if r.severity is not None else -1e9 for r in rs])  # noqa: E731
    st = rank_stability(sev(results), sev(b))
    assert st["spearman"] > 0.9 and st["top_k_jaccard"] > 0.5


# ---------- evaluation helpers ----------
def test_tpr_at_fpr_and_degenerate_inputs():
    sev = np.array([0.1, 0.2, 0.3, 0.4, 5.0, 6.0])
    pos, neg = np.array([0, 0, 0, 0, 1, 1], bool), np.array([1, 1, 1, 1, 0, 0], bool)
    assert tpr_at_fpr(sev, pos, neg, 0.25) == 1.0
    assert np.isnan(tpr_at_fpr(sev, np.zeros(6, bool), neg))


def test_select_aggregator_uses_per_kind_detection_and_restores_state(reference, evalset):
    vrs, labels = evalset
    before = reference.aggregate
    best, scores = select_aggregator(reference, vrs, labels)
    assert best in ("mean", "top2", "max") and set(scores) == {"mean", "top2", "max"}
    assert reference.aggregate == before
    assert scores[best] == max(scores.values())
    # `mean` dilutes the amplitude signal the autoencoder cannot see, so it must not beat top2/max
    assert scores["mean"] <= max(scores["top2"], scores["max"]) + 1e-9
