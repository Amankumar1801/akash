import numpy as np
import pytest
from akash_core.enums import QualityGrade
from akash_ml import metrics as M
from akash_ml.uncertainty.calibration import (
    IsotonicCalibrator,
    PlattCalibrator,
    calibrator_from_dict,
    fit_calibrator,
)
from akash_ml.uncertainty.conformal import SplitConformal, class_coverage, coverage, set_label
from akash_ml.uncertainty.ood import MahalanobisOOD
from akash_ml.uncertainty.quality import grade_quality


def overconfident(n=4000, seed=0):
    rng = np.random.default_rng(seed)
    true_p = rng.beta(0.7, 0.7, n)
    y = (rng.random(n) < true_p).astype(int)
    z = np.log(true_p / (1 - true_p)) * 2.5  # systematically overconfident
    return 1 / (1 + np.exp(-z)), y


def test_metric_basics():
    y = np.array([0, 0, 1, 1])
    assert M.pr_auc(y, np.array([0.1, 0.2, 0.8, 0.9])) == pytest.approx(1.0)
    assert M.roc_auc(y, np.array([0.9, 0.8, 0.2, 0.1])) == pytest.approx(0.0)
    r = M.prf(y, np.array([0.1, 0.6, 0.8, 0.4]), 0.5)
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (1, 1, 1, 1) and r["f1"] == pytest.approx(0.5)
    assert np.isnan(M.pr_auc(np.zeros(4, int), np.ones(4)))


def test_ece_zero_for_perfectly_calibrated():
    rng = np.random.default_rng(1)
    p = rng.random(50000)
    y = (rng.random(50000) < p).astype(int)
    assert M.ece(y, p) < 0.01


def test_threshold_chosen_on_given_data_only():
    y = np.array([0, 0, 0, 1, 1, 1])
    p = np.array([0.1, 0.2, 0.3, 0.6, 0.7, 0.9])
    t = M.best_f1_threshold(y, p)
    assert M.prf(y, p, t)["f1"] == 1.0


def test_recall_by_bin():
    y, p = np.array([1, 1, 1, 1]), np.array([0.9, 0.2, 0.9, 0.9])
    rows = M.recall_by_bin(y, p, 0.5, np.array([1.0, 1.0, 5.0, 5.0]), [0, 2, 10])
    assert rows[0]["recall"] == 0.5 and rows[1]["recall"] == 1.0


def test_group_bootstrap_resamples_groups_and_brackets_estimate():
    rng = np.random.default_rng(2)
    y = rng.integers(0, 2, 400)
    p = np.clip(y * 0.4 + rng.random(400) * 0.6, 0, 1)
    groups = np.repeat(np.arange(100), 4)
    lo, hi = M.group_bootstrap_ci(M.pr_auc, y, p, groups, 200, seed=3)
    assert lo < M.pr_auc(y, p) < hi


@pytest.mark.parametrize("method,cls", [("platt", PlattCalibrator), ("isotonic", IsotonicCalibrator)])
def test_calibration_reduces_ece_and_roundtrips(method, cls):
    p, y = overconfident()
    cal = fit_calibrator(p[:2000], y[:2000], method)
    assert isinstance(cal, cls)
    before, after = M.ece(y[2000:], p[2000:]), M.ece(y[2000:], cal.transform(p[2000:]))
    assert after < 0.5 * before and after < 0.06
    back = calibrator_from_dict(cal.to_dict())
    assert np.allclose(back.transform(p[2000:]), cal.transform(p[2000:]))


def test_auto_calibrator_choice_depends_on_data_size():
    p, y = overconfident(4000)
    assert fit_calibrator(p, y).method == "isotonic"
    assert fit_calibrator(p[:300], y[:300]).method == "platt"


def test_conformal_marginal_and_class_conditional_coverage():
    p, y = overconfident(6000, seed=3)
    cal = fit_calibrator(p[:2000], y[:2000], "platt")
    pc = cal.transform(p)
    cp = SplitConformal(0.1).fit(pc[2000:4000], y[2000:4000])
    sets = cp.predict_sets(pc[4000:])
    assert coverage(y[4000:], sets) >= 0.88
    cc = class_coverage(y[4000:], sets)
    assert cc[0] >= 0.86 and cc[1] >= 0.86, cc


def test_conformal_set_labels():
    assert set_label(np.array([True, True])) == "uncertain"
    assert set_label(np.array([False, True])) == "planet_like"
    assert set_label(np.array([True, False])) == "not_planet_like"
    assert set_label(np.array([False, False])) == "abstain"


def test_conformal_tiny_calibration_set_is_conservative():
    cp = SplitConformal(0.1).fit(np.array([0.9, 0.1]), np.array([1, 0]))
    assert cp.qhat == {0: 1.0, 1: 1.0}  # cannot honour 90% with 1 sample/class -> include all


def test_ood_flags_far_points_handles_nan_and_roundtrips():
    rng = np.random.default_rng(4)
    x = rng.normal(size=(1000, 4))
    ood = MahalanobisOOD([0, 1, 2, 3]).fit(x)
    assert ood.flag(x).mean() < 0.03
    far = np.array([[12.0, -12.0, 12.0, -12.0]])
    assert ood.flag(far)[0] and ood.percentile(far)[0] > 99.9
    nan_row = np.array([[np.nan, 0.0, 0.0, 0.0]])
    assert np.isfinite(ood.percentile(nan_row)[0])
    back = MahalanobisOOD.from_dict(ood.to_dict())
    assert np.allclose(back.percentile(far), ood.percentile(far))


@pytest.mark.parametrize("args,grade", [
    ((15, 8, 1.0, 0.0), QualityGrade.A), ((10, 5, 1.0, 0.0), QualityGrade.B),
    ((8, 3, 1.0, 0.0), QualityGrade.C), ((5, 8, 1.0, 0.0), QualityGrade.D),
    ((15, 8, 2.5, 0.0), QualityGrade.B), ((15, 8, 2.5, 0.5), QualityGrade.C)])
def test_quality_grades(args, grade):
    assert grade_quality(*args).grade == grade
