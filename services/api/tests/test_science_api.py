import json
import uuid

import numpy as np
from akash_science.agn import analyze_variability  # noqa: F401  (import check for the dependency)
from conftest import H, add_observation, make_lc, planet

REST = {"H-alpha": 6564.61, "H-beta": 4862.68, "[O III] 5007": 5008.24, "[O III] 4959": 4960.30}


def spectrum(z=0.35, n_step=2.0, seed=1, lines=tuple(REST), hi=10000.0):
    rng = np.random.default_rng(seed)
    w = np.arange(4000.0, hi, n_step)
    f = 10.0 * (w / 6000.0) ** -0.5 + rng.normal(0, 0.2, len(w))
    for name in lines:
        c = REST[name] * (1 + z)
        s = c * 300.0 / 299792.458 / 2.355
        f = f + 15.0 * np.exp(-0.5 * ((w - c) / s) ** 2)
    return w, f


def post(client, keys, w, f, who="viewer", **extra):
    body = {"wavelength_a": [float(x) for x in w], "flux": [None if np.isnan(x) else float(x) for x in f]}
    body.update(extra)
    return client.post("/v1/spectra/analyze", json=body, headers=H(keys[who]))


def test_spectrum_analysis_round_trip_with_redshift_and_disclaimer(client, keys):
    w, f = spectrum()
    r = post(client, keys, w, f, label="synthetic")
    assert r.status_code == 200
    j = r.json()
    assert j["redshift"]["status"] == "candidate_redshift"
    assert abs(j["redshift"]["candidates"][0]["z"] - 0.35) < 1e-3
    assert j["label"] == "synthetic" and len(j["input_sha256"]) == 64
    assert j["disclaimer"].startswith("AKASH assists investigation") and j["caveats"]


def test_null_flux_points_are_masked_not_fatal(client, keys):
    w, f = spectrum()
    f[5] = np.nan
    j = post(client, keys, w, f).json()
    assert j["n_masked"] == 1


def test_invalid_spectrum_is_a_422_with_a_reason(client, keys):
    w, f = spectrum()
    r = post(client, keys, w[::-1], f)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_spectrum"
    assert "increasing" in r.json()["error"]["message"]


def test_request_validation_and_size_limits(client, keys):
    w, f = spectrum()
    assert post(client, keys, w[:10], f[:10]).status_code == 422                  # too short
    assert post(client, keys, w, f, surprise=1).status_code == 422                # unknown field
    big = np.arange(20_001.0) + 4000
    assert post(client, keys, big, np.ones(20_001)).status_code == 422            # over the cap
    assert post(client, keys, w, f, label="x" * 81).status_code == 422


def test_a_full_size_spectrum_fits_the_body_limit_and_runs(client, keys):
    w = np.linspace(4000, 9000, 20_000)
    rng = np.random.default_rng(2)
    r = post(client, keys, w, 10 + rng.normal(0, 0.1, len(w)))
    assert r.status_code == 200 and r.json()["n_points"] == 20_000


def test_analysis_is_audited_without_storing_the_spectrum(client, keys, services):
    w, f = spectrum()
    post(client, keys, w, f)
    with services.context() as ctx:
        from akash_api.auth import ApiKeyStore
        rows = ApiKeyStore(ctx.conn).audit_entries("spectrum.analyze")
    assert rows and rows[-1]["outcome"] == "candidate_redshift"
    assert len(rows[-1]["resource"] or "") <= 16 and "wavelength" not in json.dumps(rows)


def test_observation_variability_reports_descriptors_with_provenance(client, services, keys):
    obj = client.post("/v1/objects/search", json={"query": "TIC 1"}, headers=H(keys["viewer"])).json()
    with services.context() as ctx:
        o = ctx.repo.get_object(uuid.UUID(obj["object_id"]))
    lc = make_lc(1, planet(make_lc(1)))
    lc.native_quality[11] = 32
    obs_id = add_observation(services, o, lc)
    r = client.get(f"/v1/observations/{obs_id}/variability", headers=H(keys["viewer"]))
    assert r.status_code == 200
    j = r.json()
    assert j["character"] in {"insufficient_data", "no_significant_variability",
                              "periodic_like", "stochastic_aperiodic"}
    assert j["n_quality_dropped"] == int((lc.native_quality != 0).sum()) >= 1 and j["provenance_id"] and len(j["input_sha256"]) == 64
    assert j["disclaimer"].startswith("AKASH assists investigation")
    assert "does not say what kind of object" in " ".join(j["caveats"])


def test_unknown_observation_is_404(client, keys):
    r = client.get(f"/v1/observations/{uuid.uuid4()}/variability", headers=H(keys["viewer"]))
    assert r.status_code == 404
