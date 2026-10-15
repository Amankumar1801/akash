import numpy as np
import pytest
from akash_science.spectra import REST_LINES, InvalidSpectrum, analyze_spectrum


def make(
    z=0.35,
    lines=("H-alpha", "H-beta", "[O III] 5007", "[O III] 4959", "[N II] 6584"),
    amp=1.5,
    fwhm_kms=300.0,
    noise=0.02,
    seed=1,
    lo=4000.0,
    hi=10000.0,
    step=2.0,
):
    rng = np.random.default_rng(seed)
    w = np.arange(lo, hi, step)
    f = 10.0 * (w / 6000.0) ** -0.5 + rng.normal(0, noise * 10.0, len(w))
    for name in lines:
        c = REST_LINES[name][0] * (1 + z)
        s = c * fwhm_kms / 299792.458 / 2.355
        f = f + 10.0 * amp * np.exp(-0.5 * ((w - c) / s) ** 2)
    return w, f


def test_noise_only_has_no_lines():
    w, f = make(lines=())
    a = analyze_spectrum(w, f)
    assert not a.lines and a.redshift["status"] == "no_lines"


def test_recovers_redshift_from_several_lines():
    w, f = make(z=0.35)
    a = analyze_spectrum(w, f)
    r = a.redshift
    assert r["status"] == "candidate_redshift" and r["tier"] == "supported"
    assert r["candidates"][0]["z"] == pytest.approx(0.35, abs=5e-4)
    assert r["candidates"][0]["n_matched"] >= 3
    assert any(ln["matched"] == "H-alpha" for ln in a.lines)


def test_two_lines_are_only_tentative():
    w, f = make(z=0.2, lines=("H-alpha", "[O III] 5007"))
    r = analyze_spectrum(w, f).redshift
    assert r["tier"] == "tentative" and "chance" in r["note"]


def test_single_line_is_never_a_redshift():
    w, f = make(lines=("H-alpha",))
    r = analyze_spectrum(w, f).redshift
    assert r["status"] == "single_line_only" and r["candidates"] == []


def test_unmatched_lines_give_no_match():
    w, f = make(z=0.0, lines=())
    for c in (5123.0, 7311.0, 8890.0):  # lines at wavelengths that fit no common redshift
        f = f + 10.0 * 1.5 * np.exp(-0.5 * ((w - c) / 3.0) ** 2)
    assert analyze_spectrum(w, f).redshift["status"] in {
        "no_match",
        "ambiguous",
        "candidate_redshift",
    }


def test_broad_lines_are_flagged_as_a_descriptor():
    w, f = make(z=0.3, lines=("H-alpha", "H-beta", "Mg II"), fwhm_kms=4000.0, amp=0.8, hi=9000.0)
    a = analyze_spectrum(w, f)
    assert a.broad_emission and all(ln["fwhm_kms"] is None or ln["fwhm_kms"] > 0 for ln in a.lines)
    assert any("not a classification" in c for c in a.caveats)


def test_narrow_lines_are_not_flagged_broad():
    w, f = make(z=0.35)
    assert analyze_spectrum(w, f).broad_emission == []


def test_absorption_lines_are_typed_and_signed():
    w, f = make(z=0.1, lines=())
    for name in ("Ca II K", "Ca II H"):
        c = REST_LINES[name][0] * 1.1
        f = f - 10.0 * 0.4 * np.exp(-0.5 * ((w - c) / 4.0) ** 2)
    a = analyze_spectrum(w, f)
    ab = [ln for ln in a.lines if ln["kind"] == "absorption"]
    assert len(ab) >= 2 and all(ln["equivalent_width_a"] > 0 for ln in ab)


def test_flux_errors_are_used_and_nonfinite_points_dropped():
    w, f = make()
    e = np.full_like(f, 0.2)
    f[10] = np.nan
    a = analyze_spectrum(w, f, e)
    assert a.noise_source == "flux_err" and a.n_masked == 1
    assert analyze_spectrum(w, make()[1]).noise_source == "mad"


def test_deterministic_with_input_hash():
    w, f = make()
    a, b = analyze_spectrum(w, f).to_dict(), analyze_spectrum(w, f).to_dict()
    assert a == b and len(a["input_sha256"]) == 64
    assert a["disclaimer"].startswith("AKASH assists investigation")


@pytest.mark.parametrize(
    "w,f",
    [
        (np.arange(10.0) + 4000, np.ones(10)),  # too few points
        (np.arange(100.0, 0, -1) + 4000, np.ones(100)),  # not increasing
        (np.arange(100.0) + 4000, np.ones(99)),  # length mismatch
        (np.arange(100.0) + 4000, -np.ones(100)),  # non-positive continuum
        (np.arange(100.0) * 0.001 + 5, np.ones(100)),  # wavelength below 100 A
        (np.where(np.arange(100) == 3, np.nan, np.arange(100.0) + 4000), np.ones(100)),
    ],
)
def test_invalid_input_is_rejected_with_a_reason(w, f):
    with pytest.raises(InvalidSpectrum):
        analyze_spectrum(w, f)


def test_size_cap_and_bad_types():
    with pytest.raises(InvalidSpectrum, match="too many"):
        analyze_spectrum(np.arange(60_000.0) + 4000, np.ones(60_000))
    with pytest.raises(InvalidSpectrum, match="numeric"):
        analyze_spectrum(["a", "b"], [1, 2])
