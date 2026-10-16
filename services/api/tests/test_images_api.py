import base64
import io

import numpy as np
from conftest import H


def galaxy(size=129, seed=1, n=1, re=8.0):
    rng = np.random.default_rng(seed)
    y, x = np.indices((size, size))
    r = np.hypot(x - size // 2, y - size // 2)
    bn = 2 * n - 1 / 3 + 0.009876 / n
    return (
        200.0 * np.exp(-bn * ((r / re) ** (1 / n) - 1)) + rng.normal(0, 1, (size, size))
    ).astype("<f4")


def pix(img, **extra):
    h, w = img.shape
    return {
        "pixels_b64": base64.b64encode(img.tobytes()).decode(),
        "width": w,
        "height": h,
        **extra,
    }


def post(client, keys, body, who="viewer"):
    return client.post("/v1/images/analyze", json=body, headers=H(keys[who]))


def test_pixels_round_trip_gives_descriptors_preview_and_disclaimer(client, keys):
    r = post(client, keys, pix(galaxy(), label="synthetic"))
    assert r.status_code == 200
    j = r.json()
    assert (
        j["status"] == "source_measured"
        and j["input_kind"] == "pixels"
        and j["label"] == "synthetic"
    )
    assert 2.0 < j["source"]["concentration"] < 3.5 and j["preview"]["width"] <= 192
    assert (
        len(base64.b64decode(j["preview"]["pixels_b64"]))
        == j["preview"]["width"] * j["preview"]["height"] * 4
    )
    assert j["disclaimer"].startswith("AKASH assists investigation") and j["caveats"]


def test_fits_upload_works(client, keys):
    from astropy.io import fits

    buf = io.BytesIO()
    fits.PrimaryHDU(galaxy()).writeto(buf)
    r = post(client, keys, {"fits_b64": base64.b64encode(buf.getvalue()).decode()})
    assert r.status_code == 200 and r.json()["input_kind"] == "fits"


def test_noise_reports_no_source_rather_than_inventing_one(client, keys):
    img = np.random.default_rng(3).normal(0, 1, (96, 96)).astype("<f4")
    j = post(client, keys, pix(img)).json()
    assert j["status"] == "no_source_detected" and j["source"] is None


def test_input_validation(client, keys):
    img = galaxy()
    assert post(client, keys, {}).status_code == 422  # neither
    assert post(client, keys, {**pix(img), "fits_b64": "AAAA"}).status_code == 422  # both
    assert post(client, keys, {"pixels_b64": "AAAA"}).status_code == 422  # no size
    assert post(client, keys, {**pix(img), "width": 100}).status_code == 422  # size mismatch
    assert post(client, keys, {**pix(img), "surprise": 1}).status_code == 422
    assert post(client, keys, {"pixels_b64": "***", "width": 16, "height": 16}).status_code == 422
    assert post(client, keys, {"fits_b64": base64.b64encode(b"nope").decode()}).status_code == 422
    wide = np.zeros((200, 520), dtype="<f4")
    assert post(client, keys, pix(wide)).status_code == 422  # side over 512
    assert post(client, keys, pix(galaxy(size=600))).status_code in (413, 422)  # body limit first
    assert (
        post(client, keys, pix(np.ones((64, 64), dtype="<f4"))).json()["error"]["code"]
        == "invalid_image"
    )


def test_the_body_limit_still_applies(client, keys):
    huge = {"fits_b64": "A" * 1_100_000}
    assert post(client, keys, huge).status_code in (413, 422)


def test_analysis_is_audited_by_hash_not_by_content(client, keys, services):
    post(client, keys, pix(galaxy()))
    from akash_api.auth import ApiKeyStore

    with services.context() as ctx:
        rows = ApiKeyStore(ctx.conn).audit_entries("image.analyze")
    assert (
        rows and rows[-1]["outcome"] == "source_measured" and len(rows[-1]["resource"] or "") <= 16
    )
