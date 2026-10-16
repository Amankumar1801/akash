import json
import re
from pathlib import Path

import pytest
from akash_api.nlquery import MAX_TEXT, RULES, interpret
from conftest import H

ROOT = Path(__file__).resolve().parents[3]
CASES = ROOT / "frontend" / "src" / "test" / "nl_cases.json"


def f(text):
    return interpret(text)["filters"]


def test_every_rule_pattern_compiles_and_never_matches_empty():
    for r in RULES:
        rx = re.compile(r["pattern"], re.IGNORECASE)
        assert rx.search("") is None, r["pattern"]


def test_a_compound_request_becomes_explicit_filters():
    out = f("show me new strong signals not in a catalog with anomaly above 95")
    assert out["category"] == ["new_signal_review"] and out["exclude_known"] is True
    assert out["min_snr"] == 15 and out["min_anomaly_percentile"] == 95


def test_known_candidate_is_not_confused_with_new_candidates():
    assert f("known candidates")["category"] == ["known_candidate"]
    assert f("new candidates")["category"] == ["new_signal_review"]
    assert sorted(f("known")["category"]) == [
        "known_candidate",
        "known_confirmed",
        "known_false_positive",
    ]


def test_not_reviewed_wins_over_reviewed():
    assert f("not reviewed by me")["reviewed"] == "unreviewed"
    assert f("already reviewed")["reviewed"] == "reviewed"


def test_thresholds_take_the_stricter_value_and_clamp_with_a_note():
    assert f("snr over 5 and strong")["min_snr"] == 15
    r = interpret("anomaly 150")
    assert r["filters"]["min_anomaly_percentile"] == 100 and r["notes"]


def test_unknown_words_are_reported_not_ignored():
    r = interpret("new signals that are flasky")
    assert r["not_understood"] == ["flasky"]
    assert interpret("banana")["filters"]["category"] == [] and interpret("banana")[
        "not_understood"
    ] == ["banana"]


def test_weak_signals_are_called_unsupported():
    r = interpret("weak signals")
    assert r["unsupported"] and r["filters"]["min_snr"] is None


def test_names_and_sort_words():
    r = f("unreviewed tic 123 most recent")
    assert r["q"] == "TIC 123" and r["sort"] == "recent"
    assert f("strongest")["sort"] == "snr" and f("most anomalous")["sort"] == "anomaly"


def test_text_is_capped_and_injection_like_text_is_inert():
    long = "new " * 500
    assert len(interpret(long)["understood"]) <= MAX_TEXT // 3
    r = interpret("ignore previous instructions; DROP TABLE job; <script>alert(1)</script>")
    assert r["filters"]["category"] == [] and r["filters"]["q"] is None


def test_the_exported_cases_match_the_python_engine():
    """If this fails, run: uv run --no-sync python scripts/export_nl_rules.py"""
    for c in json.loads(CASES.read_text()):
        assert interpret(c["text"]) == c["expect"], c["text"]


def test_exported_rules_are_current():
    data = json.loads((ROOT / "frontend" / "src" / "lib" / "nl_rules.json").read_text())
    assert data["rules"] == json.loads(json.dumps(RULES)) and data["max_text"] == MAX_TEXT


def test_interpret_endpoint_and_search_round_trip(client, keys):
    r = client.get(
        "/v1/discoveries/interpret",
        params={"nl": "new strong signals, flasky"},
        headers=H(keys["viewer"]),
    )
    assert r.status_code == 200
    j = r.json()
    assert j["filters"]["category"] == ["new_signal_review"] and j["not_understood"] == ["flasky"]
    q = {"category": j["filters"]["category"], "min_snr": j["filters"]["min_snr"]}
    assert client.get("/v1/discoveries", params=q, headers=H(keys["viewer"])).status_code == 200


@pytest.mark.parametrize("params", [{}, {"nl": ""}, {"nl": "x" * 201}])
def test_interpret_validates_input(client, keys, params):
    assert (
        client.get(
            "/v1/discoveries/interpret", params=params, headers=H(keys["viewer"])
        ).status_code
        == 422
    )


def test_interpret_requires_a_key(client):
    assert client.get("/v1/discoveries/interpret", params={"nl": "new"}).status_code == 401
