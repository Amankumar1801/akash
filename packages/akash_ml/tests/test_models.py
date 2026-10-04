import numpy as np
import pytest
from akash_ml import metrics as M
from akash_ml.transit.baseline import SnrBaseline
from akash_ml.transit.ensemble import DISAGREE_RANGE, Council, Ensemble
from akash_ml.transit.explain import bins_to_windows, occlusion_importance
from akash_ml.transit.features import CNN_SCALARS, FEATURE_NAMES, STELLAR_FEATURES
from akash_ml.transit.gbm import GBMTransitModel


def test_feature_contract(ds):
    assert ds.features.shape[1] == len(FEATURE_NAMES) == len(set(FEATURE_NAMES))
    for n in STELLAR_FEATURES:  # NaN until stellar context is supplied
        assert np.isnan(ds.features[:, FEATURE_NAMES.index(n)]).all()
    assert set(CNN_SCALARS) <= set(FEATURE_NAMES)
    assert not np.isnan(ds.features[:, [FEATURE_NAMES.index(n) for n in CNN_SCALARS[:8]]]).any()


def test_gbm_beats_snr_baseline_on_synthetic(parts):
    tr, va, te = parts["train"], parts["val"], parts["test"]
    base = M.pr_auc(te.labels, SnrBaseline().fit(tr).predict_proba(te))
    gbm = GBMTransitModel().fit(tr, va)
    assert M.pr_auc(te.labels, gbm.predict_proba(te)) > base + 0.15


def test_gbm_deterministic_and_roundtrip(parts):
    tr, va, te = parts["train"], parts["val"], parts["test"]
    a, b = GBMTransitModel(seed=3).fit(tr, va), GBMTransitModel(seed=3).fit(tr, va)
    assert np.allclose(a.predict_proba(te), b.predict_proba(te))
    back = GBMTransitModel.from_string(a.to_string())
    assert np.allclose(back.predict_proba(te), a.predict_proba(te))


def test_shap_contributions_are_additive(parts):
    tr, va, te = parts["train"], parts["val"], parts["test"]
    g = GBMTransitModel().fit(tr, va)
    c = g.contributions(te)
    assert c.shape == (len(te), len(FEATURE_NAMES) + 1)
    assert np.allclose(1 / (1 + np.exp(-c.sum(axis=1))), g.predict_proba(te), atol=1e-6)
    top = g.top_features(te, 0, k=3)
    assert len(top) == 3 and abs(top[0][1]) >= abs(top[2][1])


def test_council_flags_disagreement(parts):
    te = parts["test"]

    class Const:
        def __init__(self, v, fam):
            self.v, self.family, self.version = v, fam, "x"

        def predict_proba(self, ds):
            return np.full(len(ds), self.v)

    agree = Council({"a": Const(0.8, "a"), "b": Const(0.75, "b")}).predict(te)
    clash = Council({"a": Const(0.9, "a"), "b": Const(0.1, "b")}).predict(te)
    assert not agree.disagree.any() and clash.disagree.all()
    assert clash.range[0] == pytest.approx(0.8) and 0.8 > DISAGREE_RANGE
    ens = Ensemble([Const(0.2, "a"), Const(0.6, "a")], "a")
    assert ens.predict_proba(te)[0] == pytest.approx(0.4) and ens.spread(te)[0] == pytest.approx(0.2)
    with pytest.raises(ValueError):
        Council({})


def test_occlusion_localises_on_the_region_the_model_uses():
    g, loc = np.zeros(2001), np.zeros(201)
    loc[95:106] = -1.0  # a dip in the middle of the local view

    def predict(gv, lv):  # model that only "looks" at the local-view centre
        return float(1 / (1 + np.exp(4 * lv[90:111].mean())))  # a dip raises p

    ig, il = occlusion_importance(predict, g, loc)
    assert np.argmax(il) in range(90, 111)
    assert np.abs(ig).max() < 1e-9  # global view irrelevant to this model
    assert il[:60].max() <= 1e-9 and il[150:].max() <= 1e-9
    w = bins_to_windows(il, np.linspace(-1, 1, 201), k=1)
    assert len(w) == 1 and w[0][0] < 0.1 and w[0][1] > -0.1


def test_bins_to_windows_empty_when_no_support():
    assert bins_to_windows(np.zeros(10), np.arange(10.0)) == []
