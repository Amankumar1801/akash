import numpy as np
import pytest

torch = pytest.importorskip("torch")
from akash_ml import metrics as M  # noqa: E402
from akash_ml.transit.cnn import _COLS, CNNTransitModel, normalize_views  # noqa: E402


def test_normalize_views_convention():
    g = np.array([[1.0, 1.0, 0.9, 1.0]])
    loc = np.array([[1.0, 0.8, 1.0]])
    gn, ln = normalize_views(g, loc)
    assert ln.min() == pytest.approx(-1.0) and np.median(ln) == pytest.approx(0.0)
    assert gn.dtype == np.float32


@pytest.fixture(scope="module")
def trained(parts):
    return CNNTransitModel(seed=0).fit(parts["train"], parts["val"], epochs=40)


def test_cnn_learns_signal_and_outputs_probabilities(trained, parts):
    p = trained.predict_proba(parts["test"])
    assert p.shape == (len(parts["test"]),) and ((p >= 0) & (p <= 1)).all()
    # sanity that optimisation works: it must fit the data it was trained on...
    tr = parts["train"]
    assert M.pr_auc(tr.labels, trained.predict_proba(tr)) > 0.65
    # ...and beat chance on held-out data (small train set => modest, honestly reported)
    te = parts["test"]
    assert M.pr_auc(te.labels, p) > te.labels.mean() + 0.15


def test_cnn_deterministic_given_seed(trained, parts):
    again = CNNTransitModel(seed=0).fit(parts["train"], parts["val"], epochs=40)
    assert np.allclose(again.predict_proba(parts["test"]), trained.predict_proba(parts["test"]),
                       atol=1e-6)


def test_cnn_weights_roundtrip_with_weights_only_load(trained, parts):
    back = CNNTransitModel.from_bytes(trained.to_bytes(), trained.meta())
    assert np.allclose(back.predict_proba(parts["test"]), trained.predict_proba(parts["test"]),
                       atol=1e-6)


def test_predict_from_views_matches_batch_prediction(trained, parts):
    te = parts["test"]
    i = 3
    one = trained.predict_from_views(te.global_views[i], te.local_views[i], te.features[i, _COLS])
    assert one == pytest.approx(float(trained.predict_proba(te)[i]), abs=1e-5)


def test_unfitted_model_refuses_to_predict(parts):
    with pytest.raises(AssertionError):
        CNNTransitModel().predict_proba(parts["test"])
