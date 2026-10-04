import numpy as np
import pytest
from akash_core.errors import ValidationFailure
from akash_ml.transit.dataset import TransitDataset
from akash_ml.transit.splits import SplitManifest, assert_no_leakage, split_of


def test_split_is_deterministic_and_salted():
    assert split_of(123, "a") == split_of(123, "a")
    assert any(split_of(i, "a") != split_of(i, "b") for i in range(200))


def test_fractions_approximately_respected():
    c = SplitManifest.build(range(20000), "salt").counts()
    assert abs(c["train"] / 20000 - 0.70) < 0.02 and abs(c["test"] / 20000 - 0.10) < 0.02


def test_existing_assignments_stable_when_stars_added():
    a = SplitManifest.build(range(500), "s").assignment
    b = SplitManifest.build(range(800), "s").assignment
    assert all(a[k] == b[k] for k in a)  # the frozen test set never reshuffles


def test_no_star_straddles_splits(ds, manifest):
    idx = manifest.indices(ds.star_ids)
    assert_no_leakage(ds.star_ids, idx)
    assert sum(len(v) for v in idx.values()) == len(ds)
    assert (np.bincount(ds.star_ids)[ds.star_ids] > 1).any(), "fixture must contain multi-TCE stars"


def test_leakage_detector_fires():
    stars = np.array([1, 1, 2])
    with pytest.raises(ValidationFailure, match="LEAKAGE"):
        assert_no_leakage(stars, {"train": np.array([0]), "test": np.array([1, 2])})


def test_manifest_roundtrip_and_tamper_detection(manifest):
    d = manifest.to_json()
    assert SplitManifest.from_json(d).digest() == manifest.digest()
    k = next(iter(d["assignment"]))
    d["assignment"][k] = "test" if d["assignment"][k] != "test" else "train"
    with pytest.raises(ValidationFailure, match="digest mismatch"):
        SplitManifest.from_json(d)


def test_unknown_star_rejected(manifest):
    with pytest.raises(ValidationFailure):
        manifest.indices(np.array([10**9]))


def test_dataset_roundtrip_hash_and_subset(ds, tmp_path):
    h = ds.save(tmp_path / "d.npz")
    back = TransitDataset.load(tmp_path / "d.npz")
    assert back.content_hash() == h == ds.content_hash() and len(back) == len(ds)
    sub = ds.subset(np.arange(5))
    assert len(sub) == 5 and sub.content_hash() != h


def test_dataset_length_mismatch_rejected(ds):
    with pytest.raises(ValueError):
        TransitDataset(ds.tce_ids[:3], ds.star_ids, ds.labels, ds.global_views, ds.local_views,
                       ds.features)


def test_synthetic_set_has_both_classes_and_overlapping_snr(ds):
    assert 0.25 < ds.labels.mean() < 0.75
    snr = ds.meta["snr"]
    lo, hi = snr[ds.labels == 1], snr[ds.labels == 0]
    assert max(lo.min(), hi.min()) < min(np.median(lo), np.median(hi)), "classes must overlap in SNR"
