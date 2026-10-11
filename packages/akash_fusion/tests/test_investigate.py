import numpy as np
import pytest
from akash_core.enums import Direction, EvidenceChannel, TriageCategory, VetStatus
from akash_core.errors import ProviderError
from akash_core.schemas import Assessment
from akash_fusion.assembler import InvestigationDeps, investigate
from akash_fusion.stellar import StellarService
from akash_fusion.store import EvidenceStoreError
from akash_ml.anomaly.engine import AnomalyEngine
from akash_ml.anomaly.reference import ReferencePopulation
from akash_science.injection.models import InjectionSpec
from akash_science.lightcurve.pipeline import LightCurvePipeline
from akash_science.lightcurve.variability import extract_variability
from akash_science.synthetic_anomaly import make_lc as make_anomalous
from akash_science.synthetic_anomaly import make_population
from conftest import FakeCatalog, FakeGaia, make_lc, neighbor, planet, toi
from pydantic import ValidationError

BANNED = ("we discovered", "new planet", "proves", "confirmed new", "definitely")


def two(lc, d1, d2, p=4.0):
    t0 = float(lc.time_bjd[0])
    return make_lc(1, InjectionSpec(p, t0 + 1.0, d1, 0.1), InjectionSpec(p, t0 + 1.0 + p / 2, d2, 0.1))


def run(obj, lc, lc_prov, deps):
    return investigate(obj, lc, lc_prov, deps)


@pytest.fixture(scope="module")
def anomaly_engine():
    lcs, _ = make_population({"normal": 130}, seed=100)
    vrs = [extract_variability(x) for x in lcs]
    ref = ReferencePopulation("synthetic-normal-fusion", {"kind": "synthetic"}, seed=0)
    return AnomalyEngine(ref.fit(vrs, np.arange(len(vrs))))


# ---------- the happy path and its invariants ----------
def test_clean_planet_goes_to_review_with_a_complete_assessment(obj, lc_prov, deps):
    r = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    a = r.assessment
    assert r.outcome == "assessed" and isinstance(a, Assessment)
    assert a.triage_category == TriageCategory.NEW_SIGNAL_REVIEW
    assert a.transit.period_d.value == pytest.approx(3.2, rel=0.01)
    assert a.transit.snr > 15 and a.prediction.calibrated and a.ood is not None
    assert a.known_status.status == "none" and a.data_quality.grade.value in "ABC"
    assert set(a.vetting) >= {"odd_even", "secondary_eclipse", "transit_shape"}
    channels = {e.channel for e in r.evidence}
    assert {EvidenceChannel.OBSERVED_FACT, EvidenceChannel.MODEL_PREDICTION,
            EvidenceChannel.CATALOG_STATUS, EvidenceChannel.DATA_QUALITY,
            EvidenceChannel.CROSS_SURVEY} <= channels


def test_every_evidence_row_traces_to_a_verified_fetch(obj, lc_prov, deps, prov):
    r = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    assert r.evidence
    for e in r.evidence:
        assert e.provenance_ids, e.claim
        for pid in e.provenance_ids:
            prov.verify_chain(pid)  # raises unless the chain ends in a source_uri + sha256 root


def test_pipeline_never_fabricates_interpretations_or_discovery_language(obj, lc_prov, deps):
    r = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    assert EvidenceChannel.INTERPRETATION not in {e.channel for e in r.evidence}
    texts = [e.claim for e in r.evidence] + [x.text for x in r.decision.reasons]
    for t in texts:
        assert not any(b in t.lower() for b in BANNED), t
    ids = {e.evidence_id for e in r.evidence}
    for reason in r.assessment.triage_reasons:  # reasons can only cite evidence that exists
        assert reason.evidence_ids and set(reason.evidence_ids) <= ids
    assert set(r.assessment.conflicting_evidence) <= ids


def test_assessment_has_no_aggregate_score_and_components_stay_separate(obj, lc_prov, deps):
    a = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps).assessment
    dumped = a.model_dump()
    assert not any("score" in k for k in dumped)
    # prediction, data quality, anomaly and vetting are separate typed fields, never merged
    assert {"prediction", "data_quality", "vetting", "transit"} <= set(dumped)
    assert a.model_validate(dumped) == a


def test_deterministic_across_runs(obj, lc_prov, deps):
    lc = make_lc(1, planet(make_lc(1)))
    a, b = run(obj, lc, lc_prov, deps), run(obj, lc, lc_prov, deps)
    assert a.investigation_id != b.investigation_id
    assert a.assessment.triage_category == b.assessment.triage_category
    assert [x.rule for x in a.assessment.triage_reasons] == [x.rule for x in b.assessment.triage_reasons]
    assert a.assessment.transit == b.assessment.transit
    assert a.assessment.prediction == b.assessment.prediction


# ---------- catalog behaviour ----------
def test_known_planet_is_reported_from_the_catalog(obj, lc_prov, deps):
    deps.catalog = FakeCatalog([toi(3.2, "CP")])
    r = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    assert r.assessment.triage_category == TriageCategory.KNOWN_CONFIRMED
    assert r.assessment.known_status.status == "confirmed"
    matched = [e for e in r.evidence if e.value.get("matched")]
    assert len(matched) == 1 and matched[0].direction == Direction.SUPPORTS
    assert matched[0].value["source"] == "NASA Exoplanet Archive"


def test_known_false_positive_contradicts(obj, lc_prov, deps):
    deps.catalog = FakeCatalog([toi(3.2, "FP")])
    r = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    assert r.assessment.triage_category == TriageCategory.KNOWN_FALSE_POSITIVE
    assert any(e.direction == Direction.CONTRADICTS and e.value.get("matched") for e in r.evidence)


def test_other_catalog_entries_do_not_make_this_signal_known(obj, lc_prov, deps):
    deps.catalog = FakeCatalog([toi(9.9, "CP", "200.01")])
    r = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    assert r.assessment.triage_category == TriageCategory.NEW_SIGNAL_REVIEW
    assert r.assessment.known_status.status == "none"
    assert "hosts other catalog entries" in r.decision.reasons[0].text
    keys = [e.claim for e in r.evidence if e.channel == EvidenceChannel.CATALOG_STATUS]
    assert any("none matches" in k for k in keys) and any("does not match" in k for k in keys)


@pytest.mark.parametrize("catalog", [FakeCatalog(fail=True), None])
def test_catalog_outage_is_explicit_never_silent(obj, lc_prov, deps, catalog):
    deps.catalog = catalog
    r = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    a = r.assessment
    assert a.triage_category == TriageCategory.NEW_SIGNAL_REVIEW and a.known_status is None
    assert r.decision.reasons[0].rule == "catalog_unavailable"
    unavailable = [e for e in r.evidence if e.value.get("status") == "unavailable"]
    assert len(unavailable) == 1 and unavailable[0].direction == Direction.INCONCLUSIVE
    assert any("Catalog lookup was unavailable" in f for f in a.recommended_followup)
    if catalog is not None:
        assert any("catalog lookup failed" in w for w in r.warnings)


# ---------- cross-survey ----------
def test_capable_neighbour_is_conflicting_evidence_with_an_action(obj, lc_prov, deps):
    deps.stellar = StellarService(FakeGaia(neighbors=[neighbor(1, 8.0, 16.0)]))
    r = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    cont = [e for e in r.evidence if e.value.get("verdict") == "capable_neighbor"]
    assert len(cont) == 1 and cont[0].direction == Direction.CONTRADICTS
    assert cont[0].evidence_id in r.assessment.conflicting_evidence
    assert any("centroid" in f for f in r.assessment.recommended_followup)
    assert r.assessment.triage_category == TriageCategory.NEW_SIGNAL_REVIEW  # informs, not decides


def test_clean_neighbourhood_supports(obj, lc_prov, deps):
    r = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    cont = [e for e in r.evidence if "verdict" in e.value][0]
    assert cont.direction == Direction.SUPPORTS and cont.value["verdict"] == "none_capable"


def test_high_ruwe_adds_a_followup(obj, lc_prov, deps):
    deps.stellar = StellarService(FakeGaia(star={
        "source_id": 777, "phot_g_mean_mag": 12.0, "teff_gspphot": 5700.0, "logg_gspphot": 4.4,
        "radius_gspphot": 1.0, "ruwe": 2.5}))
    r = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    assert any("RUWE" in f for f in r.assessment.recommended_followup)
    assert any(e.value.get("ruwe") == 2.5 and e.direction == Direction.CONTRADICTS
               for e in r.evidence)


def test_gaia_stellar_parameters_flow_into_vetting(obj, lc_prov, deps):
    """A compact dwarf cannot produce a 2.6 h transit at P=3.2 d: the Gaia radius/logg must reach
    the duration-plausibility check and decide the triage."""
    deps.stellar = StellarService(FakeGaia(star={
        "source_id": 777, "phot_g_mean_mag": 12.0, "teff_gspphot": 3000.0, "logg_gspphot": 5.5,
        "radius_gspphot": 0.1, "ruwe": 1.0}))
    r = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    assert r.assessment.vetting["duration_plausibility"] == VetStatus.FAIL
    assert r.assessment.triage_category == TriageCategory.LIKELY_SYSTEMATIC
    assert r.assessment.triage_reasons[0].rule == "vetting_fail:duration_plausibility"


def test_gaia_outage_degrades_gracefully(obj, lc_prov, deps):
    class Down(FakeGaia):
        def lookup(self, o):
            raise ProviderError("gaia down")

    deps.stellar = StellarService(Down())
    r = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    assert r.assessment is not None and any("Gaia enrichment unavailable" in w for w in r.warnings)
    assert not any(e.channel == EvidenceChannel.CROSS_SURVEY for e in r.evidence)
    assert r.assessment.vetting["duration_plausibility"] == VetStatus.UNKNOWN


# ---------- eclipsing binaries: what the rules can and cannot see ----------
def test_high_contrast_binary_is_likely_systematic(obj, lc_prov, deps):
    r = run(obj, two(make_lc(1), 0.02, 0.015), lc_prov, deps)
    a = r.assessment
    assert a.triage_category == TriageCategory.LIKELY_SYSTEMATIC
    assert a.triage_reasons[0].rule == "vetting_fail:odd_even"
    assert any("odd/even" in f for f in a.recommended_followup)


def test_moderate_binary_is_surfaced_not_hidden(obj, lc_prov, deps):
    """One WARN is not decisive under the documented heuristic, so the category stays 'review',
    but the concern must appear as conflicting evidence AND as a concrete action."""
    r = run(obj, two(make_lc(1), 0.004, 0.003), lc_prov, deps)
    a = r.assessment
    assert a.triage_category == TriageCategory.NEW_SIGNAL_REVIEW
    assert a.vetting["odd_even"] == VetStatus.WARN
    assert a.conflicting_evidence and any("odd/even" in f for f in a.recommended_followup)


def test_equal_depth_binary_is_photometrically_degenerate_with_a_planet(obj, lc_prov, deps):
    """KNOWN LIMITATION, pinned on purpose: two equal eclipses per cycle look exactly like a
    planet at half the period. Nothing in photometry alone can separate them, and the system
    must not pretend otherwise."""
    r = run(obj, two(make_lc(1), 0.004, 0.004), lc_prov, deps)
    assert r.assessment.triage_category == TriageCategory.NEW_SIGNAL_REVIEW
    assert r.assessment.transit.period_d.value == pytest.approx(2.0, rel=0.02)  # the HALF period
    assert not r.assessment.conflicting_evidence


# ---------- outcomes without a candidate ----------
def test_no_signal_yields_no_assessment_by_design(obj, lc_prov, deps, store):
    r = run(obj, make_lc(5), lc_prov, deps)
    assert r.outcome == "no_transit_signal" and r.assessment is None and r.decision is None
    assert store.get_assessment(r.investigation_id) is None
    assert r.pipeline.warnings


def test_model_is_optional(obj, lc_prov, deps):
    deps.system = None
    r = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    assert r.assessment.prediction is None and r.assessment.ood is None
    assert r.assessment.triage_category == TriageCategory.NEW_SIGNAL_REVIEW
    assert not any(e.channel == EvidenceChannel.MODEL_PREDICTION for e in r.evidence)


def test_additional_signals_are_recorded_but_not_triaged(obj, lc_prov, deps):
    lc0 = make_lc(1)
    t0 = float(lc0.time_bjd[0])
    r = run(obj, make_lc(1, InjectionSpec(3.2, t0 + 1.1, 0.005, 0.11),
                         InjectionSpec(7.3, t0 + 2.0, 0.004, 0.14)), lc_prov, deps)
    assert len(r.additional_signals) == len(r.pipeline.tces) - 1
    extras = [e for e in r.evidence if e.claim.startswith("Additional periodic signal")]
    assert len(extras) == len(r.additional_signals) >= 1
    assert all(e.direction == Direction.NEUTRAL for e in extras)


# ---------- anomaly integration ----------
def test_anomaly_evidence_is_recorded_and_bridged(obj, lc_prov, deps, anomaly_engine):
    deps.anomaly = anomaly_engine
    r = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    ev = [e for e in r.evidence if e.channel == EvidenceChannel.ANOMALY]
    assert len(ev) == 1 and ev[0].value["reference"] == "synthetic-normal-fusion"
    assert "not a discovery claim" in ev[0].claim
    assert r.assessment.anomaly is not None and 0 <= r.assessment.anomaly.percentile <= 100


def test_artifact_suspect_light_curve_is_recorded_as_contradicting(obj, lc_prov, deps,
                                                                    anomaly_engine, store):
    deps.anomaly = anomaly_engine
    lc = make_anomalous("artifact_flagged", np.random.default_rng(3))
    r = run(obj, lc, lc_prov, deps)
    ev = [e for e in r.evidence if e.channel == EvidenceChannel.ANOMALY]
    assert len(ev) == 1 and ev[0].direction == Direction.CONTRADICTS
    assert ev[0].value["status"] == "artifact_suspect" and ev[0].value["artifact_reasons"]
    assert store.list_evidence(r.investigation_id, "anomaly")  # persisted even without a TCE


# ---------- persistence, matrix, immutability ----------
def test_investigation_roundtrips_through_the_store(obj, lc_prov, deps, store):
    r = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    assert store.get_assessment(r.investigation_id) == r.assessment
    stored = store.list_evidence(r.investigation_id)
    assert {e.evidence_id for e in stored} == {e.evidence_id for e in r.evidence}
    assert len(store.list_evidence(r.investigation_id, "model_prediction")) == 1


def test_evidence_is_immutable_and_corrections_supersede(obj, lc_prov, deps, store):
    r = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    old = r.evidence[0]
    with pytest.raises(ValidationError):
        old.claim = "edited"  # frozen model
    new = old.model_copy(update={"evidence_id": __import__("uuid").uuid4(), "claim": "corrected"})
    store.supersede(old.evidence_id, new)
    live = {e.evidence_id for e in store.list_evidence(r.investigation_id)}
    assert old.evidence_id not in live and new.evidence_id in live
    assert old.evidence_id in {e.evidence_id for e in
                               store.list_evidence(r.investigation_id, include_superseded=True)}
    with pytest.raises(EvidenceStoreError):
        store.supersede(__import__("uuid").uuid4(), new)


def test_evidence_matrix_exposes_source_reliability_and_agreement(obj, lc_prov, deps, prov):
    deps.catalog = FakeCatalog([toi(3.2, "CP")])
    r = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    rows = r.matrix(prov)
    assert len(rows) == len(r.evidence)
    cat = next(x for x in rows if x["result"].get("matched"))
    assert cat["source"]["uri"] == "https://exoplanetarchive.test/TAP" and cat["source"]["sha256"]
    assert cat["reliability"] == "archive_curated" and cat["agreement"] == "supports"
    sig = next(x for x in rows if x["observation"].startswith("Periodic dip search"))
    assert sig["source"]["uri"] == "https://mast.stsci.edu/synthetic"  # traced back to the fetch
    assert sig["source"]["dataset"] == "TESS-SPOC" and sig["source"]["release"] == "DR-test"
    assert all(x["version"] and x["timestamp"] and x["provenance_ids"] for x in rows)


# ---------- regressions found by reading the printed evidence matrix ----------
def test_single_model_system_reports_unknown_spread_not_zero_spread(obj, lc_prov, deps):
    """A one-member system has no ensemble spread. A zero-width interval would read as certainty;
    the fixture's system is GBM-only, so this is the case that exposed the bug."""
    assert len(deps.system.members) == 1
    r = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    p = r.assessment.prediction
    assert p.interval_90 == (0.0, 1.0)  # vacuous on purpose: 'unknown'
    ev = next(e for e in r.evidence if e.channel == EvidenceChannel.MODEL_PREDICTION)
    assert "single model" in ev.claim and ev.uncertainty["spread_defined"] is False
    assert "unknown" in ev.uncertainty["kind"]


def test_contamination_wording_when_there_are_no_neighbours(obj, lc_prov, deps):
    r = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    c = next(e for e in r.evidence if "verdict" in e.value)
    assert c.claim.startswith("No Gaia neighbours within 21")
    deps.stellar = StellarService(FakeGaia(neighbors=[neighbor(1, 8.0, 25.0)]))
    r2 = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    c2 = next(e for e in r2.evidence if "verdict" in e.value)
    assert c2.claim.startswith("None of the 1 Gaia neighbour")


def test_matrix_versions_are_not_duplicated(obj, lc_prov, deps, prov):
    rows = run(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps).matrix(prov)
    sig = next(x for x in rows if x["observation"].startswith("Periodic dip search"))
    assert sig["version"] == "lc-pipeline@1" and sig["source"]["activity"]


# ---------- progress events & cancellation (consumed by the job system) ----------
def collect(obj, lc, lc_prov, deps):
    events = []
    r = investigate(obj, lc, lc_prov, deps, progress=events.append)
    return r, events


def test_progress_events_cover_every_phase_in_order(obj, lc_prov, deps):
    from akash_fusion.progress import PHASES
    r, ev = collect(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    phases = [e.phase for e in ev]
    assert [p for p in PHASES if p in phases] == list(dict.fromkeys(phases))  # canonical order
    for phase in PHASES:  # every phase reports, even when skipped
        assert phase in phases, phase
    started = {e.phase for e in ev if e.status == "started"}
    done = {e.phase for e in ev if e.status in ("completed", "failed")}
    assert started <= done  # nothing is left 'started' forever
    assert next(e for e in ev if e.phase == "signal_search" and e.status == "completed"
                ).data["n_tces"] >= 1
    assert next(e for e in ev if e.phase == "evidence_fusion" and e.status == "completed"
                ).data["category"] == r.assessment.triage_category.value


def test_unconfigured_services_are_reported_as_skipped_not_silently_absent(obj, lc_prov, deps):
    deps.system, deps.catalog, deps.stellar = None, None, None
    _, ev = collect(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps)
    skipped = {e.phase for e in ev if e.status == "skipped"}
    assert {"stellar_enrichment", "anomaly", "ml_inference"} <= skipped


def test_no_signal_run_still_reports_a_consistent_event_stream(obj, lc_prov, deps):
    r, ev = collect(obj, make_lc(5), lc_prov, deps)
    assert r.outcome == "no_transit_signal"
    skipped = [e.phase for e in ev if e.status == "skipped"]
    assert {"ml_inference", "cross_match", "evidence_fusion"} <= set(skipped)
    assert ev[-1].phase == "persist" and ev[-1].status == "completed"


def test_cancellation_from_the_callback_aborts_before_persisting(obj, lc_prov, deps, store):
    from akash_core.errors import JobCancelled

    def cancel_at_ml(e):
        if e.phase == "ml_inference" and e.status == "started":
            raise JobCancelled("cancelled")

    inv = __import__("uuid").uuid4()
    with pytest.raises(JobCancelled):
        investigate(obj, make_lc(1, planet(make_lc(1))), lc_prov, deps, inv, cancel_at_ml)
    assert store.get_assessment(inv) is None and store.list_evidence(inv) == []


def test_progress_is_optional_and_does_not_change_results(obj, lc_prov, deps):
    lc = make_lc(1, planet(make_lc(1)))
    a = investigate(obj, lc, lc_prov, deps)
    b = investigate(obj, lc, lc_prov, deps, progress=lambda e: None)
    assert a.assessment.triage_category == b.assessment.triage_category
    assert a.assessment.transit == b.assessment.transit
