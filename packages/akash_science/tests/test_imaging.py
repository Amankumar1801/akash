import io

import numpy as np
import pytest
from akash_science.imaging import (
    InvalidImage,
    analyze_image,
    downsample_for_preview,
    read_fits_bytes,
)


def sersic(n, re=8.0, q=1.0, pa=0.0, size=129, amp=200.0, noise=1.0, seed=1, centre=None):
    rng = np.random.default_rng(seed)
    y, x = np.indices((size, size))
    cx, cy = centre or (size // 2, size // 2)
    x, y = x - cx, y - cy
    c, s = np.cos(np.radians(pa)), np.sin(np.radians(pa))
    xr, yr = c * x + s * y, -s * x + c * y
    r = np.sqrt(xr**2 + (yr / q) ** 2)
    bn = 2 * n - 1 / 3 + 0.009876 / n
    return amp * np.exp(-bn * ((r / re) ** (1 / n) - 1)) + rng.normal(0, noise, (size, size))


def test_noise_only_finds_no_source():
    a = analyze_image(np.random.default_rng(2).normal(0, 1, (100, 100)))
    assert a.status == "no_source_detected" and a.source is None


def test_a_measured_source_has_the_expected_scales_and_centroid():
    a = analyze_image(sersic(1, re=8.0))
    s = a.source
    assert a.status == "source_measured" and s["snr"] > 100
    assert s["r50_px"] == pytest.approx(8.0, rel=0.15)  # half-light radius is the input re
    assert s["centroid_xy"] == pytest.approx([64.0, 64.0], abs=0.3)


def test_concentration_orders_profiles_like_the_literature():
    c1 = analyze_image(sersic(1)).source["concentration"]
    c4 = analyze_image(sersic(4)).source["concentration"]
    assert 2.3 < c1 < 3.2 and c4 > c1 + 1.5


def test_ellipticity_and_position_angle_are_recovered():
    s = analyze_image(sersic(1, q=0.5, pa=30)).source
    assert s["ellipticity"] == pytest.approx(0.5, abs=0.08)
    assert s["position_angle_deg"] == pytest.approx(30.0, abs=6.0)
    assert analyze_image(sersic(1)).source["ellipticity"] < 0.08


def test_asymmetry_rises_with_a_companion_and_is_near_zero_when_symmetric():
    sym = analyze_image(sersic(1)).source["asymmetry"]
    img = sersic(1)
    y, x = np.indices(img.shape)
    img = img + 150 * (np.hypot(x - 80, y - 64) < 6)
    assert sym < 0.05 and analyze_image(img).source["asymmetry"] > sym + 0.2


def test_an_unresolved_core_is_called_out():
    a = analyze_image(sersic(4))
    assert any("not resolved" in c for c in a.caveats)


def test_nonfinite_pixels_are_replaced_and_counted():
    img = sersic(1)
    img[3, 3] = np.nan
    a = analyze_image(img)
    assert (
        a.n_masked == 1
        and any("non-finite" in c for c in a.caveats)
        and a.status == "source_measured"
    )


def test_deterministic_and_never_classifies():
    a, b = analyze_image(sersic(1)).to_dict(), analyze_image(sersic(1)).to_dict()
    assert a == b and len(a["input_sha256"]) == 64
    text = repr(a).lower()
    assert "spiral" not in text.replace("no morphological class", "") and "elliptical" not in text
    assert a["disclaimer"].startswith("AKASH assists investigation")


@pytest.mark.parametrize(
    "img",
    [
        np.ones((100, 100)),
        np.zeros((8, 100)),
        np.ones((600, 600)),
        np.ones((10, 10, 3)),
        np.full((50, 50), np.nan),
    ],
)
def test_invalid_images_are_rejected_with_a_reason(img):
    with pytest.raises(InvalidImage):
        analyze_image(img)


def test_non_numeric_input_is_rejected():
    with pytest.raises(InvalidImage, match="numeric"):
        analyze_image([["a", "b"]])


def test_preview_is_small_float32_and_bounded():
    p = downsample_for_preview(sersic(1, size=400))
    assert p["width"] <= 192 and p["height"] <= 192 and p["factor"] == 3
    import base64

    raw = base64.b64decode(p["pixels_b64"])
    assert len(raw) == p["width"] * p["height"] * 4 and p["vmin"] < p["vmax"]


def _fits(arr):
    from astropy.io import fits

    buf = io.BytesIO()
    fits.PrimaryHDU(arr.astype("float32")).writeto(buf)
    return buf.getvalue()


def test_fits_round_trip_and_extension_images():
    arr = sersic(1)
    assert np.allclose(read_fits_bytes(_fits(arr)), arr.astype("float32"), atol=1e-4)
    from astropy.io import fits

    buf = io.BytesIO()
    fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(arr.astype("float32"))]).writeto(buf)
    assert read_fits_bytes(buf.getvalue()).shape == arr.shape


def test_fits_oversize_header_is_refused_before_reading_pixels():
    from astropy.io import fits

    hdr = fits.Header()
    hdr["SIMPLE"], hdr["BITPIX"], hdr["NAXIS"] = True, -32, 2
    hdr["NAXIS1"], hdr["NAXIS2"] = 100000, 100000
    raw = bytes(hdr.tostring(padding=True), "ascii")
    with pytest.raises(InvalidImage, match="at most"):
        read_fits_bytes(raw)


@pytest.mark.parametrize("raw", [b"", b"not a fits file", b"SIMPLE  =" + b" " * 3000])
def test_garbage_is_not_fits(raw):
    with pytest.raises(InvalidImage):
        read_fits_bytes(raw)


def test_fits_without_a_2d_image_is_refused():
    with pytest.raises(InvalidImage, match="two-dimensional"):
        read_fits_bytes(_fits(np.ones((4, 8, 8))))
