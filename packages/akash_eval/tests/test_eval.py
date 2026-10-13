from __future__ import annotations

import math

import akash_eval.experiment as ex
import numpy as np
import pytest
from akash_eval import Cancelled, ExperimentConfig, crossing, run_experiment, summarise, wilson
from akash_science.injection.experiment import TrialResult
from akash_science.injection.models import InjectionSpec
from akash_science.synthetic import make_synthetic_lc
from pydantic import ValidationError


def test_wilson_known_values_and_edges():
    lo, hi = wilson(0, 10)  # type: ignore[misc]
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)
    lo, hi = wilson(10, 10)  # type: ignore[misc]
    assert hi == pytest.approx(1.0) and lo == pytest.approx(0.7225, abs=1e-3)
    lo, hi = wilson(50, 100)  # type: ignore[misc]
    assert lo == pytest.approx(0.4038, abs=1e-3) and hi == pytest.approx(0.5962, abs=1e-3)
    assert wilson(0, 0) is None  # no data, no claim


def test_wilson_interval_narrows_with_n():
    w = [wilson(n // 2, n) for n in (10, 100, 1000)]
    widths = [b - a for a, b in w]  # type: ignore[misc]
    assert widths[0] > widths[1] > widths[2]


def test_crossing():
    assert crossing([0, 10, 20], [0.1, 0.4, 0.9], 0.5) == pytest.approx(12.0)
    assert crossing([0, 10], [0.1, 0.4], 0.5) is None
    assert crossing([5, 10], [0.6, 0.9], 0.5) == 5


@pytest.mark.parametrize("kw", [{"n_trials": 3}, {"n_trials": 10_000}, {"n_controls": 99},
                                {"period_min_d": 5, "period_max_d": 2},
                                {"depth_min_ppm": 9000, "depth_max_ppm": 1000},
                                {"noise_source": "real"}, {"bogus": 1}, {"seed": -1}])
def test_config_rejects_bad_input(kw):
    with pytest.raises(ValidationError):
        ExperimentConfig(**kw)


def test_config_key_is_stable_and_sensitive():
    a, b = ExperimentConfig(), ExperimentConfig()
    assert a.key() == b.key() and ExperimentConfig(seed=1).key() != a.key()


def tr(snr, ok, alias=False, p=3.0, depth=2e-3):
    return TrialResult(InjectionSpec(p, 0.0, depth, 0.1), snr, ok, alias, None, None, 0)


def test_summary_bins_intervals_and_thresholds():
    res = [tr(5, False)] * 4 + [tr(8, False)] * 2 + [tr(8, True)] * 2 + [tr(20, True)] * 5
    s = summarise(ExperimentConfig(), res, (1, 10))
    assert s.n_trials == 13 and s.overall_recovery.k == 7
    first = s.by_snr[0]
    assert first.recovered.n == 4 and first.recovered.rate == 0.0 and first.recovered.hi > 0.3
    empty = next(b for b in s.by_snr if b.recovered.n == 0)
    assert empty.recovered.rate is None and empty.recovered.lo is None  # no data, no number
    assert s.snr_at_50pct is not None and s.false_alarm.k == 1  # type: ignore[union-attr]
    assert s.snr_at_90pct is not None and s.snr_at_90pct >= s.snr_at_50pct
    assert "synthetic" in s.noise_note and len(s.caveats) >= 4
    assert sum(b.recovered.n for b in s.by_period) == 13
    assert sum(b.recovered.n for b in s.by_depth) == 13


def test_threshold_is_none_when_never_reached():
    s = summarise(ExperimentConfig(), [tr(8, False)] * 5, None)
    assert s.snr_at_50pct is None and s.false_alarm is None


def test_zero_controls_means_no_false_alarm_claim():
    s = summarise(ExperimentConfig(n_controls=0), [tr(8, True)] * 4, None)
    assert s.false_alarm is None


def fake_trials(monkeypatch, log):
    def fake(mk, pipe, n, seed, period_range, depth_range):
        log.append((n, seed))
        return [tr(20, True)] * n
    monkeypatch.setattr(ex, "run_trials", fake)
    monkeypatch.setattr(ex, "run_controls", lambda mk, pipe, n, seed: (0, n))


def test_progress_chunks_and_derived_seeds(monkeypatch):
    log, prog = [], []
    fake_trials(monkeypatch, log)
    r = run_experiment(ExperimentConfig(n_trials=10, n_controls=4, seed=3),
                       progress=lambda d, t: prog.append((d, t)), chunk=4)
    assert [n for n, _ in log] == [4, 4, 2] and len({s for _, s in log}) == 3
    assert prog[-1] == (14, 14) and [d for d, _ in prog] == sorted(d for d, _ in prog)
    assert r.false_alarm.k == 0 and r.false_alarm.n == 4  # type: ignore[union-attr]


def test_cancellation_between_chunks(monkeypatch):
    fake_trials(monkeypatch, [])
    calls = {"n": 0}

    def cancelled():
        calls["n"] += 1
        return calls["n"] > 1
    with pytest.raises(Cancelled):
        run_experiment(ExperimentConfig(n_trials=12), cancelled=cancelled, chunk=4)


def test_real_pipeline_smoke_and_determinism():
    def mk(g):
        return make_synthetic_lc(g, days=8, cadence_s=1800, gap=None)
    cfg = ExperimentConfig(n_trials=4, n_controls=0, seed=2, period_min_d=1.0, period_max_d=3.0,
                           depth_min_ppm=4000, depth_max_ppm=8000)
    a, b = run_experiment(cfg, make_base=mk), run_experiment(cfg, make_base=mk)
    assert a == b and a.n_trials == 4
    assert all(not math.isnan(x.snr_expected) for x in [tr(1, True)])
    assert np.isfinite([bn.lo for bn in a.by_snr]).all()
