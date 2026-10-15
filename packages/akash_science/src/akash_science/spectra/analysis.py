"""One-dimensional spectrum analysis. Pure numpy, deterministic, no model and no network.

What it does: estimate a continuum, detect emission and absorption lines against a robust noise
estimate, and look for redshifts at which several detected lines coincide with known rest lines.
What it does not do: classify the source, confirm a redshift, or fit physical models. A redshift
here is a *candidate* with the lines that support it, and it is reported as ambiguous when the
evidence allows more than one reading.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

F64 = npt.NDArray[np.float64]
C_KMS = 299_792.458
MIN_POINTS = 50
MAX_POINTS = 50_000
MAX_LINES = 50
SCHEMA_VERSION = 1
DISCLAIMER = "AKASH assists investigation; it does not independently establish discoveries."

# Vacuum rest wavelengths in Angstrom. kind: which sign a real line of this species usually has.
REST_LINES: dict[str, tuple[float, str]] = {
    "Lyman-alpha": (1215.67, "emission"),
    "C IV": (1549.06, "emission"),
    "C III]": (1908.73, "emission"),
    "Mg II": (2798.75, "emission"),
    "[O II]": (3728.48, "emission"),
    "Ca II K": (3934.78, "absorption"),
    "Ca II H": (3969.59, "absorption"),
    "H-delta": (4102.89, "both"),
    "H-gamma": (4341.69, "both"),
    "H-beta": (4862.68, "both"),
    "[O III] 4959": (4960.30, "emission"),
    "[O III] 5007": (5008.24, "emission"),
    "H-alpha": (6564.61, "both"),
    "[N II] 6584": (6585.27, "emission"),
    "[S II] 6718": (6718.29, "emission"),
    "[S II] 6733": (6732.67, "emission"),
}
BROAD_KMS = 1000.0


class InvalidSpectrum(ValueError):
    """The input is not a usable spectrum. The message says why."""


@dataclass(frozen=True)
class SpectrumParams:
    detect_sigma: float = 4.0  # per-pixel significance to start a line
    min_pixels: int = 3  # contiguous pixels of one sign
    continuum_window_a: float = 300.0
    min_line_snr: float = 5.0  # integrated line significance needed for redshift matching
    tol_kms: float = 300.0
    z_min: float = -0.005
    z_max: float = 7.0


@dataclass
class SpectrumAnalysis:
    input_sha256: str
    n_points: int
    n_masked: int
    wavelength_range_a: tuple[float, float]
    median_dispersion_a: float
    continuum_window_px: int
    noise_sigma: float
    noise_source: str
    lines: list[dict[str, Any]]
    redshift: dict[str, Any]
    broad_emission: list[str]
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "input_sha256": self.input_sha256,
            "n_points": self.n_points,
            "n_masked": self.n_masked,
            "wavelength_range_a": list(self.wavelength_range_a),
            "median_dispersion_a": self.median_dispersion_a,
            "continuum_window_px": self.continuum_window_px,
            "noise_sigma": self.noise_sigma,
            "noise_source": self.noise_source,
            "lines": self.lines,
            "redshift": self.redshift,
            "broad_emission": self.broad_emission,
            "caveats": self.caveats,
            "disclaimer": DISCLAIMER,
        }


def _validate(wave: Any, flux: Any, err: Any) -> tuple[F64, F64, F64 | None, int]:
    try:
        w = np.asarray(wave, dtype=np.float64)
        f = np.asarray(flux, dtype=np.float64)
        e = None if err is None else np.asarray(err, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise InvalidSpectrum("wavelength and flux must be numeric arrays") from exc
    if w.ndim != 1 or f.ndim != 1 or w.shape != f.shape or (e is not None and e.shape != w.shape):
        raise InvalidSpectrum(
            "wavelength, flux and flux_err must be one-dimensional and equal length"
        )
    if len(w) > MAX_POINTS:
        raise InvalidSpectrum(f"too many points ({len(w)}); the limit is {MAX_POINTS}")
    if not np.isfinite(w).all():
        raise InvalidSpectrum("wavelength contains NaN or infinite values")
    if (w <= 0).any() or w.min() < 100.0 or w.max() > 200_000.0:
        raise InvalidSpectrum("wavelength must be in Angstrom, between 100 and 200000")
    if len(w) > 1 and not (np.diff(w) > 0).all():
        raise InvalidSpectrum("wavelength must be strictly increasing; it is not re-sorted for you")
    good = np.isfinite(f) if e is None else (np.isfinite(f) & np.isfinite(e) & (e > 0))
    n_masked = int((~good).sum())
    if int(good.sum()) < MIN_POINTS:
        raise InvalidSpectrum(f"need at least {MIN_POINTS} usable points, got {int(good.sum())}")
    return w[good], f[good], (None if e is None else e[good]), n_masked


def _running_median(y: F64, window: int) -> F64:
    """Median in a sliding window, evaluated on a coarse grid and interpolated, edge-reflected."""
    n = len(y)
    window = max(5, window | 1)
    half = window // 2
    pad = np.concatenate([y[half:0:-1], y, y[-2 : -half - 2 : -1]]) if n > half + 1 else y
    stride = max(1, window // 8)
    centres = np.arange(0, n, stride)
    if centres[-1] != n - 1:
        centres = np.append(centres, n - 1)
    meds = np.empty(len(centres))
    for k, c in enumerate(centres):
        meds[k] = np.median(pad[c : c + window])
    return np.interp(np.arange(n), centres, meds).astype(np.float64)


def _runs(sig: F64, thr: float, min_px: int) -> list[tuple[int, int, int]]:
    """(start, stop_exclusive, sign) for contiguous pixels beyond +-thr."""
    out: list[tuple[int, int, int]] = []
    for sign in (1, -1):
        mask = sign * sig >= thr
        i, n = 0, len(mask)
        while i < n:
            if mask[i]:
                j = i
                while j < n and mask[j]:
                    j += 1
                if j - i >= min_px:
                    out.append((i, j, sign))
                i = j
            else:
                i += 1
    return sorted(out)


def _fwhm_kms(
    w: F64, res: F64, a: int, b: int, sign: int, centroid: float, disp: float
) -> float | None:
    seg = sign * res[a:b]
    peak = int(np.argmax(seg)) + a
    half = sign * res[peak] / 2.0
    lo, hi = peak, peak
    while lo > 0 and sign * res[lo - 1] >= half:
        lo -= 1
    while hi < len(res) - 1 and sign * res[hi + 1] >= half:
        hi += 1
    width = float(w[hi] - w[lo]) + disp
    if width < 2.0 * disp:
        return None
    return float(C_KMS * width / centroid)


def _detect(w: F64, res: F64, sigma: F64, p: SpectrumParams, disp: float) -> list[dict[str, Any]]:
    sig = res / sigma
    dw = np.gradient(w)
    lines: list[dict[str, Any]] = []
    for a, b, sign in _runs(sig, p.detect_sigma, p.min_pixels):
        weights = np.abs(res[a:b])
        centroid = float(np.sum(w[a:b] * weights) / np.sum(weights))
        integ = float(np.sum(res[a:b] * dw[a:b]))
        err = float(np.sqrt(np.sum((sigma[a:b] * dw[a:b]) ** 2)))
        lines.append(
            {
                "wavelength_a": centroid,
                "kind": "emission" if sign > 0 else "absorption",
                "equivalent_width_a": -integ,  # convention: absorption positive, emission negative
                "snr": abs(integ) / err if err > 0 else 0.0,
                "peak_sigma": float(np.max(sign * sig[a:b])),
                "fwhm_kms": _fwhm_kms(w, res, a, b, sign, centroid, disp),
                "n_pixels": b - a,
                "matched": None,
            }
        )
    lines.sort(key=lambda d: -d["snr"])
    return lines[:MAX_LINES]


def _match(lines: list[dict[str, Any]], z: float, tol_kms: float) -> list[tuple[int, str, float]]:
    """Greedy one-to-one matches (detected index, rest name, velocity offset km/s) at redshift z."""
    pairs: list[tuple[float, int, str]] = []
    for name, (rest, kind) in REST_LINES.items():
        expected = rest * (1.0 + z)
        for i, ln in enumerate(lines):
            if kind != "both" and kind != ln["kind"]:
                continue
            off = C_KMS * (ln["wavelength_a"] - expected) / expected
            if abs(off) <= tol_kms:
                pairs.append((abs(off), i, name))
    pairs.sort()
    used_i: set[int] = set()
    used_n: set[str] = set()
    out: list[tuple[int, str, float]] = []
    for off, i, name in pairs:
        if i in used_i or name in used_n:
            continue
        used_i.add(i)
        used_n.add(name)
        rest = REST_LINES[name][0]
        out.append((i, name, C_KMS * (lines[i]["wavelength_a"] / (rest * (1.0 + z)) - 1.0)))
        _ = off
    return out


def _redshift(lines: list[dict[str, Any]], p: SpectrumParams) -> dict[str, Any]:
    strong = [ln for ln in lines if ln["snr"] >= p.min_line_snr]
    base: dict[str, Any] = {
        "status": "no_lines",
        "candidates": [],
        "tier": None,
        "note": "No lines were strong enough to look for a redshift.",
    }
    if not strong:
        return base
    if len(strong) == 1:
        base.update(
            status="single_line_only",
            note="Only one strong line was found. One line cannot fix a redshift.",
        )
        return base
    zs: set[float] = set()
    for ln in strong:
        for rest, kind in REST_LINES.values():
            if kind != "both" and kind != ln["kind"]:
                continue
            z = ln["wavelength_a"] / rest - 1.0
            if p.z_min <= z <= p.z_max:
                zs.add(round(z, 4))
    scored: list[tuple[int, float, float, list[tuple[int, str, float]]]] = []
    for z in sorted(zs):
        m = _match(strong, z, p.tol_kms)
        if len(m) >= 2:
            snr_sum = float(sum(strong[i]["snr"] for i, _, _ in m))
            scored.append((len(m), snr_sum, z, m))
    if not scored:
        base.update(
            status="no_match",
            note="Strong lines were found but no redshift makes two or more of them "
            "coincide with known rest lines.",
        )
        return base
    scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
    picked: list[tuple[int, float, float, list[tuple[int, str, float]]]] = []
    for s in scored:
        if all(abs(s[2] - q[2]) > 0.003 for q in picked):
            picked.append(s)
        if len(picked) == 3:
            break
    cands: list[dict[str, Any]] = []
    for n, _, _z, m in picked:
        wts = np.array([strong[i]["snr"] ** 2 for i, _, _ in m])
        zz = np.array([strong[i]["wavelength_a"] / REST_LINES[nm][0] - 1.0 for i, nm, _ in m])
        zr = float(np.sum(wts * zz) / np.sum(wts))
        scatter = float(np.std([off for _, _, off in _match(strong, zr, p.tol_kms)] or [0.0]))
        cands.append(
            {
                "z": zr,
                "n_matched": n,
                "z_scatter_kms": scatter,
                "matched_lines": [
                    {"rest": nm, "observed_a": strong[i]["wavelength_a"], "offset_kms": off}
                    for i, nm, off in m
                ],
            }
        )
    best_n = cands[0]["n_matched"]
    ambiguous = len(cands) > 1 and cands[1]["n_matched"] >= best_n
    for ln in lines:
        ln["matched"] = None
    for c in cands[:1]:
        for ml in c["matched_lines"]:
            for ln in lines:
                if ln["wavelength_a"] == ml["observed_a"]:
                    ln["matched"] = ml["rest"]
    tier = "supported" if best_n >= 3 else "tentative"
    note = (
        "More than one redshift explains the lines about equally well; "
        "this cannot be resolved from the "
        "lines alone."
        if ambiguous
        else "Two lines can coincide by chance; treat as tentative until another line "
        "or a second spectrum agrees."
        if tier == "tentative"
        else "Three or more lines agree. This is a candidate redshift, not a confirmed one."
    )
    return {
        "status": "ambiguous" if ambiguous else "candidate_redshift",
        "candidates": cands,
        "tier": tier,
        "note": note,
    }


def analyze_spectrum(
    wavelength_a: Any, flux: Any, flux_err: Any = None, params: SpectrumParams | None = None
) -> SpectrumAnalysis:
    p = params or SpectrumParams()
    w, f, e, n_masked = _validate(wavelength_a, flux, flux_err)
    sha = hashlib.sha256(w.tobytes() + f.tobytes()).hexdigest()
    disp = float(np.median(np.diff(w)))
    win = int(min(max(9, round(p.continuum_window_a / disp)), 401, max(9, len(w) // 2)))
    cont = _running_median(f, win)
    if not (cont > 0).all():
        raise InvalidSpectrum(
            "the continuum is not positive everywhere; flux must be on a positive scale"
        )
    res = f / cont - 1.0
    if e is not None:
        sigma = e / cont
        source = "flux_err"
    else:
        mad = float(np.median(np.abs(res - np.median(res))))
        sigma = np.full_like(res, 1.4826 * mad if mad > 0 else 1e-12)
        source = "mad"
    lines = _detect(w, res, sigma, p, disp)
    z = _redshift(lines, p)
    broad = sorted(
        {
            str(ln["matched"] or f"{ln['wavelength_a']:.0f} A")
            for ln in lines
            if ln["kind"] == "emission"
            and ln["fwhm_kms"] is not None
            and ln["fwhm_kms"] > BROAD_KMS
        }
    )
    caveats = [
        "The continuum is a running median, so lines broader than the window are "
        "partly absorbed into it.",
        "Matches use a fixed velocity tolerance; a blend or a sky-subtraction residual "
        "can pass as a line.",
        "Broad emission lines occur in active galactic nuclei but also in other objects; "
        "this is a descriptor, "
        "not a classification.",
    ]
    if source == "mad":
        caveats.append(
            "No flux errors were given, so noise was estimated from the scatter "
            "of the spectrum itself."
        )
    if n_masked:
        caveats.append(f"{n_masked} points with non-finite flux or error were dropped.")
    return SpectrumAnalysis(
        input_sha256=sha,
        n_points=len(w),
        n_masked=n_masked,
        wavelength_range_a=(float(w[0]), float(w[-1])),
        median_dispersion_a=disp,
        continuum_window_px=win,
        noise_sigma=float(np.median(sigma)),
        noise_source=source,
        lines=lines,
        redshift=z,
        broad_emission=broad,
        caveats=caveats,
    )
