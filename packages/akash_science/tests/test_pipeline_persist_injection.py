import json

import numpy as np
import pytest
from akash_core.enums import ProvRelation
from akash_core.schemas import ProvenanceRecord
from akash_science.config import PipelineConfig, SearchConfig
from akash_science.injection.experiment import (
    match_tce,
    run_controls,
    run_trials,
    summarize_by_snr,
)
from akash_science.injection.models import InjectionSpec, expected_snr, trapezoid_model
from akash_science.lightcurve.pipeline import LightCurvePipeline
from akash_science.lightcurve.types import TCE
from akash_science.persist import persist_result, result_to_json
from akash_science.synthetic import make_synthetic_lc
from conftest import with_injection


# ---------- pipeline ----------
def test_config_hash_stable_and_sensitive():
    assert PipelineConfig().hash() == PipelineConfig().hash()
    assert PipelineConfig().hash() != PipelineConfig(search=SearchConfig(snr_threshold=9.0)).hash()


def test_pipeline_is_deterministic(base, planet_spec):
    lc = with_injection(base, planet_spec)
    a, b = LightCurvePipeline().run(lc), LightCurvePipeline().run(lc)
    assert a.tces[0].tce == b.tces[0].tce
    assert np.array_equal(a.flux_detrended, b.flux_detrended)


def test_pipeline_reports_counts_and_noise(base, planet_spec):
    r = LightCurvePipeline().run(with_injection(base, planet_spec))
    assert r.counts["input"] == len(base.time_bjd) and r.counts["dropped_flagged"] >= 1
    assert 300 < r.noise_1h_ppm < 900 and len(r.segments) == 2  # 2 orbits split by the gap


def test_too_little_data_returns_warning_not_exception(base):
    short = type(base)(base.time_bjd[:50], base.flux[:50], base.flux_err[:50], base.sap_flux[:50],
                       base.native_quality[:50], {})
    r = LightCurvePipeline().run(short)
    assert r.tces == [] and r.warnings


def test_transit_survives_quality_and_clipping(base):
    """A very deep dip must not be removed by the upward-only clip or the detrender."""
    spec = InjectionSpec(4.0, float(base.time_bjd[0]) + 1.0, 0.02, 0.15)
    r = LightCurvePipeline().run(with_injection(base, spec))
    assert r.tces and r.tces[0].tce.depth_frac == pytest.approx(0.02, rel=0.2)


# ---------- injection primitives ----------
def test_trapezoid_geometry():
    t = np.linspace(-0.5, 0.5, 100001)
    s = InjectionSpec(1.0, 0.0, 0.01, 0.2, ingress_fraction=0.1)
    m = trapezoid_model(t, s)
    assert m.min() == pytest.approx(0.99) and m[np.abs(t) > 0.101].min() == 1.0
    flat = np.abs(t) < 0.08
    assert np.allclose(m[flat], 0.99)
    area = (1 - m).sum() * (t[1] - t[0])
    assert area == pytest.approx(0.01 * (0.2 - 0.02), rel=1e-3)  # depth * (T14 - ingress)


def test_expected_snr_scales_with_depth_and_inverse_noise(base):
    t = base.time_bjd
    s = InjectionSpec(3.0, float(t[0]) + 1, 0.001, 0.1)
    s2 = InjectionSpec(3.0, float(t[0]) + 1, 0.002, 0.1)
    assert expected_snr(t, 1e-3, s2) == pytest.approx(2 * expected_snr(t, 1e-3, s), rel=1e-6)
    assert expected_snr(t, 2e-3, s) == pytest.approx(0.5 * expected_snr(t, 1e-3, s), rel=1e-6)


def mk_tce(p, t0, dur=0.1):
    return TCE(1, p, (p, p), t0, dur, 0.001, 10, 10, 5)


def test_match_tce_exact_alias_and_wrong():
    s = InjectionSpec(3.0, 100.0, 0.001, 0.1)
    assert match_tce([mk_tce(3.01, 100.02)], s)[:2] == (True, False)
    assert match_tce([mk_tce(1.5, 100.0)], s)[:2] == (False, True)     # half-period alias
    assert match_tce([mk_tce(6.0, 100.0)], s)[:2] == (False, True)     # double-period alias
    assert match_tce([mk_tce(3.0, 101.0)], s)[:2] == (False, False)    # right period, wrong epoch
    assert match_tce([mk_tce(4.1, 100.0)], s)[:2] == (False, False)
    assert match_tce([], s)[:2] == (False, False)


def test_summarize_by_snr_bins():
    from akash_science.injection.experiment import TrialResult
    sp = InjectionSpec(3, 0, 0.001, 0.1)
    tr = [TrialResult(sp, 10, True, False, 3, 9, 1), TrialResult(sp, 11, False, True, None, None, 1),
          TrialResult(sp, 2, False, False, None, None, 0)]
    rows = summarize_by_snr(tr, [0, 5, 20])
    assert rows[0]["n"] == 1 and rows[0]["recovery_frac"] == 0.0
    assert rows[1]["n"] == 2 and rows[1]["recovery_frac"] == 0.5 and rows[1]["alias_frac"] == 0.5


def test_small_experiment_end_to_end_and_reproducible():
    pipe = LightCurvePipeline()
    mk = lambda rng: make_synthetic_lc(rng, days=20.0)  # noqa: E731
    a = run_trials(mk, pipe, 4, seed=5, depth_range=(2e-3, 4e-3), period_range=(1.5, 6.0))
    b = run_trials(mk, pipe, 4, seed=5, depth_range=(2e-3, 4e-3), period_range=(1.5, 6.0))
    assert [t.recovered for t in a] == [t.recovered for t in b]
    assert sum(t.recovered for t in a) >= 3  # deep signals must be recovered
    hits, n = run_controls(mk, pipe, 3, seed=9)
    assert (hits, n) == (0, 3)


# ---------- persistence + provenance ----------
def test_persist_links_provenance_to_source(base, planet_spec, prov, artifacts):
    root = prov.add(ProvenanceRecord(entity_type="raw_fits", activity="fetch:test", code_version="t",
                                     sha256="ab" * 32, source_uri="https://example/x"))
    norm = prov.add(ProvenanceRecord(entity_type="normalized_lightcurve", activity="normalize",
                                     code_version="t"))
    prov.link(norm.prov_id, root.prov_id, ProvRelation.WAS_DERIVED_FROM)
    res = LightCurvePipeline().run(with_injection(base, planet_spec))
    rec, js, npz = persist_result(res, norm.prov_id, artifacts, prov, "t")
    assert rec.activity.startswith("lc-pipeline@1:") and res.config_hash[:12] in rec.activity
    assert {r.prov_id for r in prov.lineage(rec.prov_id)} == {root.prov_id, norm.prov_id}
    stored = json.loads(artifacts.get(js.sha256))
    assert stored["tces"][0]["tce"]["period_d"] == pytest.approx(3.2, rel=0.01)
    assert {v["name"] for v in stored["tces"][0]["vetting"]} >= {"odd_even", "secondary_eclipse"}
    assert result_to_json(res)["config_hash"] == res.config_hash


def test_no_usable_segments_returns_warning_with_correct_field_types(base):
    # 300 isolated cadences, each > max_gap apart -> every segment has 1 point
    n = 300
    t = base.time_bjd[0] + np.arange(n) * 1.0
    iso = type(base)(t, np.full(n, 1000.0), np.ones(n), np.full(n, 1000.0),
                     np.zeros(n, np.int32), {})
    r = LightCurvePipeline().run(iso)
    assert r.tces == [] and r.warnings == ["no usable segments"] and r.segments == []


def test_acceptance_recovery_above_snr_9_frozen():
    """Frozen Phase 2 acceptance: every injection with expected SNR >= 9 is recovered.
    (Deterministic seeds; see docs/evaluation/phase2-injection-recovery.md.)"""
    pipe = LightCurvePipeline()
    mk = lambda rng: make_synthetic_lc(rng)  # noqa: E731
    trials = run_trials(mk, pipe, 6, seed=21, depth_range=(1.5e-3, 3e-3), period_range=(1.5, 10.0))
    strong = [t for t in trials if t.snr_expected >= 9.0]
    assert len(strong) >= 4, "test must exercise the regime it claims to"
    assert all(t.recovered for t in strong), [(t.spec.period_d, t.snr_expected) for t in strong]
