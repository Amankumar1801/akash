import pytest
from akash_api.discovery import Filters, apply, signal_strength, sort_cards
from conftest import H, submit, wait_done


def finished(client, keys, who="researcher", query="TIC 1", **kw):
    inv = submit(client, keys[who], query, **kw).json()["investigation_id"]
    wait_done(client, H(keys[who]), inv)
    return inv


def get(client, keys, params="", who="researcher"):
    return client.get(f"/v1/discoveries{params}", headers=H(keys[who]))


def card(cat="new_signal_review", pct=None, snr=None, known=None, name="TIC 1", mine=None,
         t=1.0, nrev=0):
    return {"investigation_id": name + cat, "name": name, "triage_category": cat,
            "anomaly": {"percentile": pct, "reference_population": "p", "category": "c"}
            if pct is not None else None,
            "transit": {"snr": snr, "period_d": 3, "depth_ppm": 1} if snr is not None else None,
            "known_status": known, "finished_at": t,
            "review": {"n_reviewers": nrev, "mine": mine, "labels": []}}


def F(**kw):
    base = dict(categories=set(), exclude_known=False, min_anomaly=None, min_snr=None,
                reviewed="any", q=None, sort="triage")
    return Filters(**{**base, **kw})


# ---------- ranking logic (no combined score, documented order) ----------
def test_triage_sort_puts_review_worthy_categories_first_then_anomaly_then_recency():
    cs = [card("known_confirmed", 99), card("likely_systematic", 90),
          card("new_signal_review", 40, t=1), card("new_signal_review", 80, t=1),
          card("models_disagree", 10), card("new_signal_review", 80, t=9)]
    out = sort_cards(cs, "triage")
    assert [c["triage_category"] for c in out][:3] == ["new_signal_review"] * 3
    assert [(c["anomaly"]["percentile"], c["finished_at"]) for c in out[:3]] == [
        (80, 9), (80, 1), (40, 1)]
    assert out[3]["triage_category"] == "models_disagree" and out[-1][
        "triage_category"] == "known_confirmed"


def test_missing_values_sort_last_not_first():
    cs = [card(pct=None, name="a"), card(pct=5, name="b")]
    assert [c["name"] for c in sort_cards(cs, "anomaly")] == ["b", "a"]
    assert [c["name"] for c in sort_cards([card(snr=None, name="a"), card(snr=2, name="b")],
                                          "snr")] == ["b", "a"]


def test_filters_compose_and_unknown_values_do_not_pass_numeric_filters():
    cs = [card("new_signal_review", 95, 20, name="A"), card("new_signal_review", 50, 20, name="B"),
          card("known_confirmed", 99, 30, known="confirmed", name="C"),
          card("insufficient_data", None, None, name="D"),
          card("new_signal_review", 97, 20, known="candidate", name="E")]
    names = lambda f: [c["name"] for c in apply(cs, f)]  # noqa: E731
    assert names(F(min_anomaly=90, exclude_known=True, sort="recent")) == ["A"]
    assert "D" not in names(F(min_anomaly=0)) and "D" in names(F())
    assert set(names(F(categories={"insufficient_data"}))) == {"D"}
    assert set(names(F(q="b"))) == {"B"}
    assert "C" not in names(F(exclude_known=True)) and "E" not in names(F(exclude_known=True))


def test_reviewed_filter_uses_my_label_only():
    cs = [card(name="x", mine="interesting"), card(name="y", nrev=3)]
    assert [c["name"] for c in apply(cs, F(reviewed="reviewed"))] == ["x"]
    assert [c["name"] for c in apply(cs, F(reviewed="unreviewed"))] == ["y"]


@pytest.mark.parametrize("snr,want", [(None, "none"), (3, "weak"), (7, "moderate"),
                                      (14.9, "moderate"), (15, "strong")])
def test_signal_strength_bands(snr, want):
    assert signal_strength(snr) == want


# ---------- endpoint ----------
def test_feed_card_has_every_field_and_no_combined_score(client, keys):
    inv = finished(client, keys)
    body = get(client, keys).json()
    c = next(x for x in body["items"] if x["investigation_id"] == inv)
    for k in ("name", "triage_category", "anomaly", "prediction", "transit", "signal_strength",
              "known_status", "data_quality", "vetting", "n_conflicts", "recommended_followup",
              "review", "ra_deg", "dec_deg"):
        assert k in c
    assert not any("score" in k for k in c) and "review queue" in body["ranking"]["caveat"]
    assert "does not independently establish" in body["disclaimer"]
    assert body["total"] >= 1 and body["scanned"] >= 1


def test_no_signal_investigations_are_not_candidates(client, keys):
    finished(client, keys, query="TIC 2")
    assert get(client, keys).json()["total"] == 0


def test_feed_is_private_but_admin_sees_all(client, keys):
    finished(client, keys)
    assert get(client, keys, who="researcher2").json()["total"] == 0
    assert get(client, keys, who="admin").json()["total"] == 1


def test_latest_investigation_per_object_only(client, keys):
    finished(client, keys, mode="deep")
    finished(client, keys, mode="quick")
    assert get(client, keys).json()["total"] == 1


def test_review_state_round_trips_through_the_feed(client, keys):
    inv = finished(client, keys)
    client.post(f"/v1/investigations/{inv}/labels", json={"label": "interesting"},
                headers=H(keys["researcher"]))
    c = get(client, keys).json()["items"][0]
    assert c["review"]["mine"] == "interesting" and c["review"]["n_reviewers"] == 1
    assert get(client, keys, "?reviewed=unreviewed").json()["total"] == 0
    assert get(client, keys, "?reviewed=reviewed").json()["total"] == 1


def test_query_validation(client, keys):
    for bad in ("?category=discovery", "?min_anomaly_percentile=101", "?sort=score",
                "?limit=0", "?limit=101", "?reviewed=maybe", "?q=" + "x" * 61, "?offset=-1"):
        assert get(client, keys, bad).status_code in (400, 422), bad
    assert client.get("/v1/discoveries").status_code == 401


def test_paging_and_filters_via_http(client, keys):
    finished(client, keys)
    assert get(client, keys, "?limit=1&offset=5").json()["items"] == []
    assert get(client, keys, "?exclude_known=true&min_snr=1").status_code == 200
    assert get(client, keys, "?category=insufficient_data").json()["total"] == 0


def test_sky_points_are_private_compact_and_labelled(client, keys):
    inv = finished(client, keys)
    s = client.get("/v1/sky", headers=H(keys["researcher"])).json()
    p = s["points"][0]
    assert p["investigation_id"] == inv and 0 <= p["ra_deg"] < 360 and -90 <= p["dec_deg"] <= 90
    assert set(p) == {"investigation_id", "name", "ra_deg", "dec_deg", "category",
                      "anomaly_percentile"}
    assert "not a survey map" in s["note"]
    assert client.get("/v1/sky", headers=H(keys["researcher2"])).json()["points"] == []
