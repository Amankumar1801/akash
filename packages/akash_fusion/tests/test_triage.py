from uuid import uuid4

import pytest
from akash_core.enums import QualityGrade, TriageCategory, VetStatus
from akash_data.base import CatalogRecord
from akash_fusion.catalog_match import CatalogMatch
from akash_fusion.stellar import ContaminationAssessment, Neighbor
from akash_fusion.triage import ModelView, TriageConfig, TriageInputs, triage

NAMES = ("odd_even", "secondary_eclipse", "transit_shape", "periodicity_coverage",
         "systematics_coincidence", "duration_plausibility", "implied_radius")
P, W, F = VetStatus.PASS, VetStatus.WARN, VetStatus.FAIL


def mk(vet=None, grade=QualityGrade.A, n=8, model="planet_like", **kw) -> TriageInputs:
    v = {k: P for k in NAMES}
    v.update(vet or {})
    mv = None if model is None else ModelView(0.8, model, kw.pop("ood", False),
                                               kw.pop("disagree", False), uuid4())
    base = dict(quality_grade=grade, quality_evidence=uuid4(), n_transits=n,
                signal_evidence=uuid4(), vetting=v, vetting_evidence={k: uuid4() for k in v},
                catalog_evidence=uuid4(), model=mv)
    base.update(kw)
    return TriageInputs(**base)


def known(status):
    rec = CatalogRecord("NASA Exoplanet Archive", "toi", "100.01", {}, status, "q", "u")
    return CatalogMatch(rec, status, 3.2, "exact", 0.0)


def all_ids(x: TriageInputs) -> set:
    ids = {x.quality_evidence, x.signal_evidence, x.catalog_evidence, *x.vetting_evidence.values()}
    if x.model:
        ids.add(x.model.evidence_id)
    if x.anomaly_evidence:
        ids.add(x.anomaly_evidence)
    return ids


def test_default_is_new_signal_review_with_sourced_reasons():
    x = mk()
    d = triage(x)
    assert d.category == TriageCategory.NEW_SIGNAL_REVIEW
    assert {r.rule for r in d.reasons} >= {"no_catalog_match", "vetting_no_decisive_failure",
                                           "model_not_excluding"}


def test_every_reason_points_at_known_evidence_in_every_branch():
    cases = [mk(), mk(vet={"odd_even": F}), mk(grade=QualityGrade.D), mk(disagree=True),
             mk(model="not_planet_like"), mk(vet={"odd_even": W, "transit_shape": W}),
             mk(catalog_match=known("confirmed")), mk(model=None),
             mk(catalog_available=False)]
    for x in cases:
        d = triage(x)
        assert d.reasons
        for r in d.reasons:
            assert r.evidence_ids and set(r.evidence_ids) <= all_ids(x), r.rule


@pytest.mark.parametrize("status,cat", [("confirmed", TriageCategory.KNOWN_CONFIRMED),
                                        ("candidate", TriageCategory.KNOWN_CANDIDATE),
                                        ("false_positive", TriageCategory.KNOWN_FALSE_POSITIVE)])
def test_catalog_match_is_reported_and_takes_precedence(status, cat):
    x = mk(vet={"odd_even": F}, grade=QualityGrade.D, catalog_match=known(status))
    d = triage(x)
    assert d.category == cat and d.reasons[0].rule.startswith("catalog_period_match")
    assert "not decided by AKASH" in d.reasons[0].text


def test_insufficient_data_rules():
    assert triage(mk(grade=QualityGrade.D)).category == TriageCategory.INSUFFICIENT_DATA
    d = triage(mk(n=1))
    assert d.category == TriageCategory.INSUFFICIENT_DATA and "unverified" in d.reasons[0].text
    assert triage(mk(n=2, grade=QualityGrade.C)).category != TriageCategory.INSUFFICIENT_DATA


def test_hard_vetting_failures_beat_everything_below_them():
    for check in ("odd_even", "secondary_eclipse", "duration_plausibility"):
        d = triage(mk(vet={check: F}, disagree=True))
        assert d.category == TriageCategory.LIKELY_SYSTEMATIC
        assert d.reasons[0].rule == f"vetting_fail:{check}"
    # a FAIL on a non-hard check (transit_shape has no FAIL state in practice) counts as a warn
    assert triage(mk(vet={"transit_shape": F})).category == TriageCategory.NEW_SIGNAL_REVIEW


def test_warn_count_is_the_documented_heuristic():
    one = mk(vet={"transit_shape": W})
    two = mk(vet={"transit_shape": W, "implied_radius": W})
    assert triage(one).category == TriageCategory.NEW_SIGNAL_REVIEW
    d = triage(two)
    assert d.category == TriageCategory.LIKELY_SYSTEMATIC and len(d.reasons) == 2
    assert triage(two, TriageConfig(n_warn_decisive=3)).category == TriageCategory.NEW_SIGNAL_REVIEW
    # warns outside warn_count_checks never count
    assert triage(mk(vet={"periodicity_coverage": W, "duration_plausibility": W})
                  ).category == TriageCategory.NEW_SIGNAL_REVIEW


def test_systematics_need_two_independent_indicators():
    flagged = {"systematics_coincidence": W}
    assert triage(mk(vet=flagged)).category == TriageCategory.NEW_SIGNAL_REVIEW
    assert triage(mk(anomaly_artifact_suspect=True, anomaly_evidence=uuid4())
                  ).category == TriageCategory.NEW_SIGNAL_REVIEW
    both = mk(vet=flagged, anomaly_artifact_suspect=True, anomaly_evidence=uuid4())
    d = triage(both)
    assert d.category == TriageCategory.LIKELY_SYSTEMATIC and d.reasons[0].rule == \
        "systematics_corroborated" and len(d.reasons[0].evidence_ids) == 2


def test_model_disagreement_routes_to_a_human():
    d = triage(mk(disagree=True))
    assert d.category == TriageCategory.MODELS_DISAGREE
    assert any("Models disagree" in f for f in d.followups)


def test_classifier_rejection_is_labelled_as_a_model_prediction():
    d = triage(mk(model="not_planet_like"))
    assert d.category == TriageCategory.LIKELY_SYSTEMATIC
    assert "MODEL PREDICTION" in d.reasons[0].text
    # out-of-distribution inputs make the classifier's rejection untrustworthy
    assert triage(mk(model="not_planet_like", ood=True)).category == \
        TriageCategory.NEW_SIGNAL_REVIEW
    assert triage(mk(model="uncertain")).category == TriageCategory.NEW_SIGNAL_REVIEW


def test_unavailable_catalog_is_not_reported_as_no_match():
    d = triage(mk(catalog_available=False))
    assert d.category == TriageCategory.NEW_SIGNAL_REVIEW
    assert d.reasons[0].rule == "catalog_unavailable" and "UNVERIFIED" in d.reasons[0].text
    assert any("Catalog lookup was unavailable" in f for f in d.followups)
    assert "no_catalog_match" in {r.rule for r in triage(mk()).reasons}


def test_star_with_other_catalog_entries_is_stated():
    d = triage(mk(star_has_other_entries=True))
    assert "hosts other catalog entries" in d.reasons[0].text


def test_without_a_model_triage_still_works():
    d = triage(mk(model=None))
    assert d.category == TriageCategory.NEW_SIGNAL_REVIEW
    assert "model_not_excluding" not in {r.rule for r in d.reasons}


def test_every_warn_or_fail_yields_a_followup():
    for check in ("odd_even", "secondary_eclipse", "transit_shape", "implied_radius",
                  "periodicity_coverage", "systematics_coincidence", "duration_plausibility"):
        for st in (W, F):
            assert triage(mk(vet={check: st})).followups, (check, st)
    assert triage(mk()).followups == []


def test_contamination_binarity_and_quality_followups():
    cont = ContaminationAssessment([Neighbor("n", 5.0, 15.0, 3.0)], 1, 0, 0.004, 21.0)
    d = triage(mk(contamination=cont, binarity_suspect=True, grade=QualityGrade.C))
    text = " ".join(d.followups)
    assert "centroid" in text and "RUWE" in text and "Data quality is low" in text
    assert "out-of-distribution" in " ".join(triage(mk(ood=True)).followups)
    assert "Observe additional transits" in " ".join(triage(mk(n=3)).followups)


def test_triage_is_deterministic_and_never_claims_a_discovery():
    x = mk(vet={"odd_even": W})
    a, b = triage(x), triage(x)
    assert a.category == b.category and [r.rule for r in a.reasons] == [r.rule for r in b.reasons]
    assert "discover" not in " ".join(c.value for c in TriageCategory)
    for inp in (mk(), mk(model="not_planet_like"), mk(catalog_match=known("confirmed"))):
        for r in triage(inp).reasons:
            low = r.text.lower()
            assert not any(w in low for w in ("we discovered", "new planet", "proves", "confirmed new"))
