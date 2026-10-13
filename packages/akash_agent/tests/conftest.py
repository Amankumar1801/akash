from __future__ import annotations

import pytest
from akash_agent import StaticView

PRED = "11111111-aaaa-4aaa-8aaa-000000000001"
CAT = "22222222-aaaa-4aaa-8aaa-000000000002"
OBS = "33333333-aaaa-4aaa-8aaa-000000000003"
POISON = "44444444-aaaa-4aaa-8aaa-000000000004"


def row(eid, channel, agreement, observation, result=None, uncertainty=None, source=None):
    return {"evidence_id": eid, "channel": channel, "agreement": agreement,
            "observation": observation, "result": result or {}, "uncertainty": uncertainty,
            "reliability": "measured", "created_by": "pipeline", "version": "p@1",
            "source": source or {"source": "TESS", "dataset": "SPOC", "release": "R1"},
            "provenance_ids": []}


def make_view(poison: str | None = None) -> StaticView:
    ev = [
        row(OBS, "observed_fact", "supports", "Transit depth 0.0102 at period 3.5 days",
            {"depth": 0.0102, "period_d": 3.5}),
        row(CAT, "catalog_status", "neutral", "No catalog match", {"status": "none"}),
        row(PRED, "model_prediction", "supports", "Calibrated planet probability 0.91",
            {"p": 0.91}, {"conformal": ["planet"]}),
    ]
    if poison:
        ev.append(row(POISON, "observed_fact", "neutral", poison))
    a = {"triage_category": "new_signal_review",
         "triage_reasons": [{"rule": "no_catalog_match", "evidence_ids": [OBS, CAT]}],
         "conflicting_evidence": []}
    return StaticView(a, ev, {OBS: [{"activity": "bls", "entity_type": "result",
                                     "code_version": "1", "sha256": "ab" * 32}]})


@pytest.fixture
def view():
    return make_view()
