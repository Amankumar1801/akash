import json

import httpx
import pytest
from akash_core.errors import ProviderError
from akash_core.schemas import AstronomicalObject, ObjectAlias
from akash_data.base import ObsFilter
from akash_data.providers.exoplanet_archive import ExoplanetArchiveProvider, aggregate_status
from akash_data.providers.gaia import GaiaProvider
from akash_data.providers.mast import KEPLER_LC, TESS_SPOC, MastLightCurveProvider
from akash_data.providers.simbad import SimbadClient
from akash_data.providers.tap import TapClient, parse_tap_json
from conftest import client_for, form, json_resp, make_fits, tap_json


def obj(**aliases):
    return AstronomicalObject(
        ra_deg=301.5, dec_deg=44.4, canonical_name="t",
        aliases=[ObjectAlias(namespace=k, identifier=v, source="t") for k, v in aliases.items()])


def test_parse_tap_shapes():
    assert parse_tap_json(tap_json(["a", "b"], [[1, 2]])) == [{"a": 1, "b": 2}]
    assert parse_tap_json([{"a": 1}]) == [{"a": 1}]
    with pytest.raises(ProviderError):
        parse_tap_json({"weird": 1})


def test_simbad_by_identifier_builds_safe_adql_and_parses():
    seen = {}

    def h(req):
        seen.update(form(req))
        return json_resp(tap_json(["oid", "main_id", "ra", "dec", "pmra", "pmdec", "plx_value"],
                                  [[1, "KIC 8462852", 301.56, 44.45, -10.3, -10.4, 2.2]]))

    s = SimbadClient(TapClient(client_for(h), "http://simbad")).by_identifier("KIC 8462852")
    assert s[0].main_id == "KIC 8462852" and s[0].pmra == -10.3
    assert "i.id = 'KIC 8462852'" in seen["query"] and seen["format"] == "json"


def test_simbad_rejects_injection_before_any_request():
    def h(req):
        raise AssertionError("no request should be made")

    with pytest.raises(Exception):
        SimbadClient(TapClient(client_for(h), "http://s")).by_identifier("x'; drop")


def test_simbad_cone_sorted_by_separation():
    def h(req):
        return json_resp(tap_json(["oid", "main_id", "ra", "dec", "pmra", "pmdec", "plx_value"],
                                  [[1, "far", 10.001, 10.0, None, None, None],
                                   [2, "near", 10.0, 10.0001, None, None, None]]))

    out = SimbadClient(TapClient(client_for(h), "http://s")).cone(10.0, 10.0, 5.0)
    assert [o.main_id for o in out] == ["near", "far"]


def test_gaia_uses_uppercase_params_and_returns_sorted():
    seen = {}

    def h(req):
        seen.update(form(req))
        return json_resp(tap_json(["source_id", "ra", "dec"], [[2, 10.002, 10.0], [1, 10.0, 10.0]]))

    g = GaiaProvider(client_for(h))
    rows = g.cone(10.0, 10.0, 5.0)
    assert [r["source_id"] for r in rows] == [1, 2] and seen["REQUEST"] == "doQuery"
    assert "gaiadr3.gaia_source" in seen["QUERY"]


def test_exoplanet_archive_status_mapping():
    def h(req):
        q = form(req)["query"]
        if "from toi" in q:
            return json_resp([{"tid": 5, "toi": 700.01, "tfopwg_disp": "CP"},
                              {"tid": 5, "toi": 700.02, "tfopwg_disp": "FP"}])
        return json_resp([{"kepid": 9, "kepoi_name": "K00001.01", "koi_disposition": "FALSE POSITIVE"}])

    p = ExoplanetArchiveProvider(client_for(h))
    recs = p.lookup(obj(TIC="5", KIC="9"))
    assert [r.status for r in recs] == ["confirmed", "false_positive", "false_positive"]
    assert all(r.query and r.source_uri for r in recs)  # provenance material present
    assert aggregate_status([r.status for r in recs]) == "confirmed"


def test_aggregate_status_precedence():
    assert aggregate_status([]) == "none"
    assert aggregate_status([None]) == "none"
    assert aggregate_status(["false_positive", "candidate"]) == "candidate"
    assert aggregate_status(["false_positive"]) == "false_positive"


def mast_handler(rows, products, files=None):
    def h(req):
        if req.method == "POST":
            r = json.loads(form(req)["request"])
            if r["service"] == "Mast.Caom.Cone":
                return json_resp({"status": "COMPLETE", "data": rows})
            return json_resp({"status": "COMPLETE", "data": products[r["params"]["obsid"]]})
        return httpx.Response(200, content=(files or {})[str(req.url.params["uri"])])
    return h


TESS_ROWS = [
    dict(obsid=11, obs_id="o1", obs_collection="TESS", dataproduct_type="timeseries",
         provenance_name="SPOC", target_name="261136679", sequence_number=1, t_min=1, t_max=2),
    dict(obsid=12, obs_id="o2", obs_collection="TESS", dataproduct_type="timeseries",
         provenance_name="SPOC", target_name="261136679", sequence_number=2, t_min=3, t_max=4),
    dict(obsid=13, obs_id="o3", obs_collection="TESS", dataproduct_type="timeseries",
         provenance_name="SPOC", target_name="999", sequence_number=1),  # neighbour star
    dict(obsid=14, obs_id="o4", obs_collection="TESS", dataproduct_type="image",
         provenance_name="SPOC", target_name="261136679", sequence_number=1),  # not a LC
]


def prods(name):
    return [{"productSubGroupDescription": "LC", "productFilename": name, "dataURI": f"mast:{name}", "size": 0},
            {"productSubGroupDescription": "DVT", "productFilename": "dv.fits", "dataURI": "mast:dv"}]


def test_mast_lists_only_matching_target_lightcurves():
    h = mast_handler(TESS_ROWS, {"11": prods("a_lc.fits"), "12": prods("b_lc.fits")})
    p = MastLightCurveProvider(client_for(h), TESS_SPOC)
    refs = p.list_observations(obj(TIC="261136679"), ObsFilter())
    assert [r.native_obs_id for r in refs] == ["a_lc.fits", "b_lc.fits"]
    assert all(r.meta["identity_match"] == "alias" for r in refs)


def test_mast_segment_filter_and_limit():
    h = mast_handler(TESS_ROWS, {"11": prods("a_lc.fits"), "12": prods("b_lc.fits")})
    p = MastLightCurveProvider(client_for(h), TESS_SPOC)
    assert len(p.list_observations(obj(TIC="261136679"), ObsFilter(segments=(2,)))) == 1
    assert len(p.list_observations(obj(TIC="261136679"), ObsFilter(max_observations=1))) == 1


def test_mast_positional_fallback_is_flagged():
    h = mast_handler(TESS_ROWS[:1], {"11": prods("a_lc.fits")})
    refs = MastLightCurveProvider(client_for(h), TESS_SPOC).list_observations(obj(), ObsFilter())
    assert refs[0].meta["identity_match"] == "positional"


def test_kepler_target_name_format():
    assert KEPLER_LC.target_name("8462852") == "kplr008462852"


def test_mast_truncated_download_detected():
    data = make_fits()
    p = [{"productSubGroupDescription": "LC", "productFilename": "a_lc.fits",
          "dataURI": "mast:a", "size": len(data) + 10}]
    h = mast_handler(TESS_ROWS[:1], {"11": p}, {"mast:a": data})
    prov = MastLightCurveProvider(client_for(h), TESS_SPOC)
    ref = prov.list_observations(obj(TIC="261136679"), ObsFilter())[0]
    with pytest.raises(ProviderError, match="truncated"):
        prov.fetch(ref)


def test_mast_error_status_raises():
    def h(req):
        return json_resp({"status": "ERROR", "msg": "bad"})

    with pytest.raises(ProviderError):
        MastLightCurveProvider(client_for(h), TESS_SPOC).list_observations(obj(), ObsFilter())


def test_gaia_drops_a_column_the_archive_rejects_and_still_returns_the_rest():
    seen: list[str] = []

    def h(req):
        q = form(req)["QUERY"]
        seen.append(q)
        if "ruwe" in q:  # the archive does not know this column
            return httpx.Response(400, text='<INFO name="QUERY_STATUS">ERROR: unknown column ruwe</INFO>')
        cols = [c.strip() for c in q.split("FROM")[0].replace("SELECT TOP 1", "").replace("SELECT", "").split(",")]
        return json_resp(tap_json(cols, [[7] + [1.0] * (len(cols) - 1)]))

    g = GaiaProvider(client_for(h))
    obj = AstronomicalObject(ra_deg=1.0, dec_deg=2.0, canonical_name="s", anchor_namespace="GAIA_DR3",
                             aliases=[ObjectAlias(namespace="GAIA_DR3", identifier="7", source="t")])
    rec = g.lookup(obj)[0]
    assert g.dropped == ["ruwe"] and "ruwe" not in rec.values and rec.values["teff_gspphot"] == 1.0
    assert "ruwe" not in g.last_query
    n = len(seen)
    g.lookup(obj)
    assert len(seen) == n + 2  # main + radius query only: the column set is remembered


def test_client_error_carries_the_servers_explanation():
    c = client_for(lambda req: httpx.Response(400, text="ERROR:   Column 'foo'\n not found"))
    with pytest.raises(ProviderError, match="Column 'foo' not found"):
        c.get("http://x")


def _gaia_obj():
    return AstronomicalObject(ra_deg=1.0, dec_deg=2.0, canonical_name="s", anchor_namespace="GAIA_DR3",
                              aliases=[ObjectAlias(namespace="GAIA_DR3", identifier="7", source="t")])


def test_gaia_radius_comes_from_the_astrophysical_parameters_table():
    seen: list[str] = []

    def h(req):
        q = form(req)["QUERY"]
        seen.append(q)
        if "astrophysical_parameters" in q:
            return json_resp(tap_json(["radius_gspphot", "radius_flame"], [[None, 1.12]]))
        if "radius" in q.split("FROM")[0]:  # gaia_source has no radius column
            return httpx.Response(400, text="unknown column radius")
        return json_resp(tap_json(["source_id", "ra", "dec", "teff_gspphot"], [[7, 1.0, 2.0, 5855.0]]))

    g = GaiaProvider(client_for(h))
    rec = g.lookup(_gaia_obj())[0]
    assert rec.values["radius_flame"] == 1.12 and rec.values["teff_gspphot"] == 5855.0
    assert not g.dropped and "astrophysical_parameters" in rec.query


def test_gaia_radius_failure_keeps_the_rest_of_the_record():
    def h(req):
        if "astrophysical_parameters" in form(req)["QUERY"]:
            return httpx.Response(400, text="nope")
        return json_resp(tap_json(["source_id", "ra", "dec"], [[7, 1.0, 2.0]]))

    g = GaiaProvider(client_for(h))
    rec = g.lookup(_gaia_obj())[0]
    assert rec.values["source_id"] == 7 and "radius_flame" not in rec.values
    assert g.dropped == ["gaiadr3.astrophysical_parameters"]
