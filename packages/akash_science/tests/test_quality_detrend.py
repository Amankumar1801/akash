import numpy as np
import pytest
from akash_data.lightcurve import NormalizedLightCurve
from akash_science.config import DetrendConfig, QualityConfig
from akash_science.lightcurve.detrend import biweight_location, biweight_trend, detrend_segments
from akash_science.lightcurve.quality import apply_quality, split_segments, upper_clip_mask


def lc(t, f, q=None):
    n = len(t)
    return NormalizedLightCurve(t, f, np.ones(n), f, np.zeros(n, np.int32) if q is None else q, {})


def test_flagged_and_nonfinite_dropped_but_flag_times_kept():
    t = np.arange(10.0) + 2458000
    f = np.full(10, 100.0)
    f[3] = np.nan
    q = np.zeros(10, np.int32)
    q[5] = 32
    r = apply_quality(lc(t, f, q), QualityConfig())
    assert len(r.time) == 8 and r.counts["dropped_flagged"] == 1 and r.counts["dropped_nonfinite"] == 1
    assert list(r.flagged_time) == [t[5]]
    assert np.median(r.flux) == pytest.approx(1.0)


def test_allowed_bits_keep_benign_flags():
    t = np.arange(10.0)
    q = np.zeros(10, np.int32)
    q[2] = 32
    assert len(apply_quality(lc(t, np.ones(10), q), QualityConfig(allowed_quality_bits=32)).time) == 10


def test_upper_clip_removes_spikes_but_never_dips():
    rng = np.random.default_rng(0)
    r = rng.normal(0, 1e-3, 1000)
    r[10], r[20] = 0.05, -0.05  # spike up, dip down (a transit-like event)
    keep, _ = upper_clip_mask(r, 5.0)
    assert not keep[10] and keep[20]


def test_split_segments_on_gaps_and_drops_tiny_runs():
    t = np.concatenate([np.arange(100) * 0.01, 5 + np.arange(100) * 0.01, 9 + np.arange(5) * 0.01])
    segs = split_segments(t, 0.5, 50)
    assert [(s.start, s.stop) for s in segs] == [(0, 100), (100, 200)]


def test_biweight_resists_outliers():
    x = np.concatenate([np.ones(100), [50.0, -50.0]])
    assert biweight_location(x) == pytest.approx(1.0, abs=1e-6)


def test_detrend_removes_variability_and_preserves_transit_depth():
    rng = np.random.default_rng(3)
    t = np.arange(0, 20, 0.01)
    star = 1 + 0.01 * np.sin(2 * np.pi * t / 6.0)
    f = star + rng.normal(0, 2e-4, len(t))
    f[(t > 10) & (t < 10.1)] -= 0.002  # 0.1 d, 2000 ppm box
    segs = [slice(0, len(t))]
    tr = detrend_segments(t, f, segs, DetrendConfig(window_days=0.75))
    res = f / tr
    # 1% sinusoid (~7000 ppm rms) -> ~noise + window-curvature bias (~250 ppm at extrema)
    assert np.std(f[t < 8]) / np.std(res[t < 8]) > 15 and np.std(res[t < 8]) < 4e-4
    depth = 1 - np.mean(res[(t > 10.02) & (t < 10.08)])
    assert depth == pytest.approx(0.002, rel=0.15)


def test_masking_transit_protects_depth_from_short_window():
    t = np.arange(0, 6, 0.01)
    f = np.ones(len(t))
    box = (t > 3) & (t < 3.4)
    f[box] -= 0.002
    cfg = DetrendConfig(window_days=0.6)  # window barely longer than the 0.4 d transit
    unmasked = 1 - np.mean((f / biweight_trend(t, f, cfg))[box])
    masked = 1 - np.mean((f / biweight_trend(t, f, cfg, mask=box))[box])
    assert masked > unmasked and masked == pytest.approx(0.002, rel=0.01)


def test_no_interpolation_across_gap():
    t = np.concatenate([np.arange(0, 5, 0.01), np.arange(8, 13, 0.01)])
    f = np.concatenate([np.full(500, 1.0), np.full(500, 2.0)])
    segs = split_segments(t, 0.5, 50)
    tr = detrend_segments(t, f, segs, DetrendConfig())
    assert tr[:500].mean() == pytest.approx(1.0) and tr[500:].mean() == pytest.approx(2.0)
