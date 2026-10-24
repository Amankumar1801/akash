import httpx
import pytest
from akash_core.errors import AmbiguousIdentity, ObjectNotFound
from akash_data.identity.resolver import Resolver
from akash_data.providers.gaia import GaiaProvider
from akash_data.providers.simbad import SimbadClient
from akash_data.providers.tap import TapClient
from conftest import client_for, form, json_resp, tap_json

SIM_COLS = ["oid", "main_id", "ra", "dec", "pmra", "pmdec", "plx_value"]


def make_resolver(repo, simbad_rows, idents, gaia_rows=None, calls=None):
    def simbad(req):
        if calls is not None:
            calls.append(form(req)["query"])
        q = form(req)["query"]
        if "FROM ident WHERE oidref" in q:
            return json_resp(tap_json(["id"], [[i] for i in idents]))
        return json_resp(tap_json(SIM_COLS, simbad_rows))

    def gaia(req):
        if calls is not None:
            calls.append(form(req)["QUERY"])
        return json_resp(tap_json(["source_id", "ra", "dec"], gaia_rows or []))

    g = GaiaProvider(client_for(gaia)) if gaia_rows is not None else None
    return Resolver(repo, SimbadClient(TapClient(client_for(simbad), "http://s")), g)


BOYAJIAN = [[7, "KIC 8462852", 301.5644, 44.4569, -10.3, -10.4, 2.2]]


def test_resolves_alias_with_gaia_anchor_from_simbad_ids(repo):
    r = make_resolver(repo, BOYAJIAN, ["KIC 8462852", "TIC 185336364", "Gaia DR3 2081900940499099136", "HD 1"])
    o = r.resolve("KIC 8462852")
    assert o.anchor_namespace == "GAIA_DR3" and o.alias("TIC") == "185336364"
    assert o.alias("GAIA_DR3") == "2081900940499099136"
    assert repo.links_for(o.object_id)[0].method == "simbad_alias"


def test_second_resolve_by_other_alias_hits_cache_no_network(repo):
    calls = []
    r = make_resolver(repo, BOYAJIAN, ["KIC 8462852", "TIC 185336364"], calls=calls)
    first = r.resolve("KIC 8462852")
    n = len(calls)
    again = r.resolve("TIC 185336364")
    assert again.object_id == first.object_id and len(calls) == n


def test_not_found(repo):
    with pytest.raises(ObjectNotFound):
        make_resolver(repo, [], []).resolve("TIC 1")


def test_name_matching_multiple_is_ambiguous(repo):
    rows = BOYAJIAN + [[8, "other", 10.0, 10.0, None, None, None]]
    with pytest.raises(AmbiguousIdentity) as e:
        make_resolver(repo, rows, []).resolve("some name")
    assert set(e.value.candidates) == {"KIC 8462852", "other"}


def test_coords_crowded_field_is_ambiguous_but_isolated_resolves(repo):
    close = [[1, "a", 10.0, 10.0, None, None, None], [2, "b", 10.0, 10.0002, None, None, None]]
    with pytest.raises(AmbiguousIdentity):
        make_resolver(repo, close, []).resolve("10.0 10.0")
    one = [[1, "a", 10.0, 10.0001, None, None, None]]
    assert make_resolver(repo, one, ["a"]).resolve("10.0 10.0").canonical_name == "a"


def test_gaia_crossmatch_propagates_pm_and_adds_alias(repo):
    calls = []
    rows = [[5, "hi-pm", 100.0, 0.0, 1000.0, 2000.0, 50.0]]
    r = make_resolver(repo, rows, ["hi-pm"], gaia_rows=[[999, 100.0044, 0.0089]], calls=calls)
    o = r.resolve("hi-pm")
    gaia_q = [c for c in calls if "gaia_source" in c][0]
    assert "100.00444444" in gaia_q and "0.00888889" in gaia_q  # propagated, not the J2000 position
    assert o.alias("GAIA_DR3") == "999" and o.anchor_namespace == "GAIA_DR3"
    assert repo.links_for(o.object_id)[0].method == "gaia_cone_pm_propagated"


def test_gaia_ambiguous_match_recorded_but_not_adopted(repo):
    rows = [[5, "star", 100.0, 0.0, None, None, None]]
    gaia_rows = [[1, 100.0, 0.0001], [2, 100.0, 0.0002]]
    o = make_resolver(repo, rows, ["star"], gaia_rows=gaia_rows).resolve("star")
    assert o.alias("GAIA_DR3") is None and o.anchor_namespace == "POSITION"
    link = repo.links_for(o.object_id)[0]
    assert link.ambiguous and link.n_candidates == 2


def _resolver_with_gaia(repo, gaia_handler):
    def simbad(req):
        q = form(req)["query"]
        if "FROM ident WHERE oidref" in q:
            return json_resp(tap_json(["id"], [["star"]]))
        return json_resp(tap_json(SIM_COLS, [[5, "star", 100.0, 0.0, None, None, None]]))

    return Resolver(repo, SimbadClient(TapClient(client_for(simbad), "http://s")),
                    GaiaProvider(client_for(gaia_handler)))


def test_object_cached_without_gaia_anchor_is_healed_on_next_resolve(repo):
    state = {"rows": [[1, 100.0, 0.0001], [2, 100.0, 0.0002]]}  # ambiguous the first time
    r = _resolver_with_gaia(
        repo, lambda req: json_resp(tap_json(["source_id", "ra", "dec"], state["rows"])))
    first = r.resolve("star")
    assert first.alias("GAIA_DR3") is None
    state["rows"] = [[77, 100.0, 0.0001]]  # Gaia now returns one clear match
    again = r.resolve("star")
    assert again.object_id == first.object_id
    assert again.alias("GAIA_DR3") == "77" and again.anchor_namespace == "GAIA_DR3"
    assert repo.find_by_alias("GAIA_DR3", "77") is not None  # persisted, not just returned


def test_heal_keeps_object_when_gaia_is_down(repo):
    state = {"down": False}

    def gaia(req):
        if state["down"]:
            return httpx.Response(500)
        return json_resp(tap_json(["source_id", "ra", "dec"], []))

    r = _resolver_with_gaia(repo, gaia)
    first = r.resolve("star")
    state["down"] = True
    assert r.resolve("star").object_id == first.object_id
