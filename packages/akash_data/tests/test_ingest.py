import json

import httpx
from akash_core.schemas import AstronomicalObject, ObjectAlias
from akash_data.ingest import ObservationService
from akash_data.providers.mast import TESS_SPOC, MastLightCurveProvider
from conftest import client_for, form, json_resp, make_fits

OBJ = AstronomicalObject(ra_deg=301.5, dec_deg=44.4, canonical_name="t",
                         aliases=[ObjectAlias(namespace="TIC", identifier="261136679", source="t")])


class Archive:
    """Fake MAST: 3 sectors; sector 2 file is corrupt; sector 3 download fails once."""

    def __init__(self):
        self.downloads: list[str] = []
        self.files = {"mast:s1": make_fits(seg=1), "mast:s2": b"<html>gateway error</html>",
                      "mast:s3": make_fits(seg=3, n=400)}
        self.fail_s3 = True

    def handler(self, req):
        if req.method == "POST":
            r = json.loads(form(req)["request"])
            if r["service"] == "Mast.Caom.Cone":
                return json_resp({"status": "COMPLETE", "data": [
                    dict(obsid=i, obs_id=f"o{i}", obs_collection="TESS", dataproduct_type="timeseries",
                         provenance_name="SPOC", target_name="261136679", sequence_number=i)
                    for i in (1, 2, 3)]})
            i = r["params"]["obsid"]
            return json_resp({"status": "COMPLETE", "data": [{
                "productSubGroupDescription": "LC", "productFilename": f"s{i}_lc.fits",
                "dataURI": f"mast:s{i}", "size": len(self.files[f"mast:s{i}"])}]})
        uri = str(req.url.params["uri"])
        self.downloads.append(uri)
        if uri == "mast:s3" and self.fail_s3:
            self.fail_s3 = False
            return httpx.Response(500)
        return httpx.Response(200, content=self.files[uri])


def service(repo, prov, artifacts, arch):
    http = client_for(arch.handler, max_retries=0)
    repo.save_object(OBJ)
    return ObservationService(MastLightCurveProvider(http, TESS_SPOC), artifacts, repo, prov, "test")


def test_ingest_partial_failure_quarantine_and_provenance(repo, prov, artifacts):
    arch = Archive()
    res = service(repo, prov, artifacts, arch).ingest(OBJ)

    assert [o.native_obs_id for o in res.observations] == ["s1_lc.fits"]
    assert [n for n, _ in res.quarantined] == ["s2_lc.fits"]          # corrupt -> quarantined
    assert [n for n, _ in res.errors] == ["s3_lc.fits"]                # transient -> reported
    # every stored observation's provenance chain is rooted in a verified fetch
    obs = res.observations[0]
    prov.verify_chain(obs.provenance_id)
    root = prov.lineage(obs.provenance_id)[0]
    assert root.source_uri.startswith("https://mast.stsci.edu") and root.sha256 and root.release == "DR27"
    assert obs.dataset == "TESS-SPOC" and obs.release == "DR27"
    # corrupt raw bytes are kept but flagged
    import akash_core.ids as ids
    bad_sha = ids.sha256_bytes(arch.files["mast:s2"])
    assert artifacts.is_quarantined(bad_sha)[0]


def test_reingest_downloads_only_what_is_missing(repo, prov, artifacts):
    arch = Archive()
    svc = service(repo, prov, artifacts, arch)
    svc.ingest(OBJ)
    first = list(arch.downloads)
    res = svc.ingest(OBJ)  # s3 now succeeds; s1 must NOT be re-downloaded
    assert res.skipped_existing == 1
    new = arch.downloads[len(first):]
    assert "mast:s1" not in new
    assert {o.native_obs_id for o in res.observations} == {"s1_lc.fits", "s3_lc.fits"}
    assert len(repo.list_observations(OBJ.object_id)) == 2


def test_listing_is_cached(repo, prov, artifacts):
    arch = Archive()
    svc = service(repo, prov, artifacts, arch)
    svc.ingest(OBJ)
    calls = {"n": 0}
    orig = svc.provider.list_observations
    svc.provider.list_observations = lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), orig(*a, **k))[1]
    svc.ingest(OBJ)
    assert calls["n"] == 0
