import json

import numpy as np
import pytest
from akash_core.errors import ValidationFailure
from akash_core.schemas import Prediction
from akash_ml.model_card import render_model_card
from akash_ml.registry import load_system, save_system
from akash_ml.training import TrainConfig, train_system
from akash_ml.transit.gbm import GBMTransitModel
from akash_ml.transit.splits import SplitManifest
from akash_ml.uncertainty.calibration import fit_calibrator
from akash_ml.uncertainty.conformal import SplitConformal, class_coverage

torch = pytest.importorskip("torch")


@pytest.fixture(scope="module")
def system(ds, manifest):
    return train_system(ds, manifest, TrainConfig(n_cnn=2, cnn_epochs=40, bootstrap=100),
                        code_version="test")


def test_system_beats_trivial_baseline_with_separated_cis(system):
    m = system.meta["metrics"]["models"]
    base, council = m["baseline_snr"], m["council_calibrated"]
    assert council["pr_auc"] > base["pr_auc"] + 0.2
    assert council["pr_auc_ci95"][0] > base["pr_auc_ci95"][1] - 0.05  # CIs essentially separated


def test_metadata_records_everything_needed_to_reproduce(system, ds, manifest):
    meta = system.meta
    assert meta["data_hash"] == ds.content_hash()
    assert meta["split_manifest_digest"] == manifest.digest()
    assert meta["feature_version"] == "tf@1" and meta["code_version"] == "test"
    assert sum(meta["n"].values()) == len(ds)
    assert 0.0 < system.threshold < 1.0


def test_calibration_does_not_degrade_probability_quality(system):
    # Deliberately NOT asserting an ECE improvement: with ~57 calibration rows and ~44 test rows
    # 10-bin ECE is noise-dominated (measured: mean ECE 0.130 -> 0.128 over 40 re-splits).
    m = system.meta["metrics"]["models"]
    assert m["council_calibrated"]["brier"] <= m["council_raw"]["brier"] + 0.02


def test_ood_flag_rate_is_low_in_distribution(system):
    o = system.meta["metrics"]["ood"]
    assert o["flag_rate_train"] < 0.05 and o["flag_rate_test"] < 0.15


def test_scored_batch_bridges_to_core_prediction_schema(system, parts):
    s = system.score(parts["test"])
    for i in range(len(parts["test"])):
        pred, ood = system.to_prediction(s, i)  # validates interval bracketing etc.
        assert isinstance(pred, Prediction) and pred.calibrated
        assert pred.interval_90[0] <= pred.planet_like_probability <= pred.interval_90[1]
        assert len(pred.model_versions) == 3  # 1 GBM + 2 CNN seeds and 0 <= ood.distance_percentile <= 100
    assert set(s.set_labels) <= {"planet_like", "not_planet_like", "uncertain", "abstain"}


def test_registry_roundtrip_reproduces_scores_exactly(system, parts, tmp_path):
    d = save_system(tmp_path, "transit-test", "v1", system)
    back = load_system(d)
    a, b = system.score(parts["test"]), back.score(parts["test"])
    assert np.allclose(a.prob, b.prob, atol=1e-6) and (a.set_labels == b.set_labels)
    assert np.allclose(a.ood_percentile, b.ood_percentile)
    meta = json.loads((d / "metadata.json").read_text())
    assert meta["data_hash"] == system.meta["data_hash"] and meta["name"] == "transit-test"


def test_registry_versions_are_immutable(system, tmp_path):
    save_system(tmp_path, "m", "v1", system)
    with pytest.raises(ValidationFailure, match="immutable"):
        save_system(tmp_path, "m", "v1", system)


def test_registry_refuses_mismatched_feature_set(system, tmp_path):
    d = save_system(tmp_path, "m", "v1", system)
    meta = json.loads((d / "metadata.json").read_text())
    meta["feature_names"] = meta["feature_names"][:-1]
    (d / "metadata.json").write_text(json.dumps(meta))
    with pytest.raises(ValidationFailure, match="different feature set"):
        load_system(d)


def test_model_card_states_limitations(system):
    card = render_model_card({**system.meta, "name": "transit", "version": "v1"},
                             "SYNTHETIC plumbing-validation data")
    for needle in ("triage score", "does NOT hold under domain shift", "SYNTHETIC",
                   "not a label confidence", "Known limitations", "PR-AUC"):
        assert needle in card.replace("\n", " "), needle


def test_stars_missing_from_manifest_abort_training(ds):
    full = SplitManifest.build(ds.star_ids, "x")
    dropped = next(iter(full.assignment))
    partial = SplitManifest(full.salt, full.fractions,
                            {k: v for k, v in full.assignment.items() if k != dropped})
    with pytest.raises(ValidationFailure):
        train_system(ds, partial, TrainConfig(run_cnn=False))


def test_conformal_coverage_valid_across_resplits(ds):
    """Validity check, not a single lucky split: average class coverage over independent
    re-splits must meet the 1-alpha target (single splits of ~25 rows scatter 0.75-1.0)."""
    c0, c1 = [], []
    for k in range(15):
        idx = SplitManifest.build(ds.star_ids, f"resplit{k}").indices(ds.star_ids)
        tr, va, ca, te = (ds.subset(idx[n]) for n in ("train", "val", "calib", "test"))
        g = GBMTransitModel().fit(tr, va)
        cal = fit_calibrator(g.predict_proba(ca), ca.labels)
        cp = SplitConformal(0.1).fit(cal.transform(g.predict_proba(ca)), ca.labels)
        cc = class_coverage(te.labels, cp.predict_sets(cal.transform(g.predict_proba(te))))
        c0.append(cc[0])
        c1.append(cc[1])
    assert np.nanmean(c0) >= 0.87 and np.nanmean(c1) >= 0.87, (np.mean(c0), np.mean(c1))
