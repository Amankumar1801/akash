"""Morphology descriptors for a single-band image, in numpy only.

Measures: background level and noise, the brightest connected source, its centroid and flux, the
radii enclosing 20, 50 and 80 percent of the light, concentration C = 5 log10(r80 / r20), rotational
asymmetry A with the expected noise contribution removed, and shape from second moments.

It does NOT assign a morphological class (spiral, elliptical, merger) or a redshift. Those need
calibrated multi-band data and a validated method; the numbers here describe one image and are
sensitive to resolution, depth and the cutout size.
"""

from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

F64 = npt.NDArray[np.float64]
MIN_SIDE = 16
MAX_SIDE = 512
MIN_SOURCE_PIXELS = 8
PREVIEW_SIDE = 192
SCHEMA_VERSION = 1
DISCLAIMER = "AKASH assists investigation; it does not independently establish discoveries."


class InvalidImage(ValueError):
    """The input is not a usable image. The message says why."""


@dataclass
class ImageAnalysis:
    input_sha256: str
    width: int
    height: int
    n_masked: int
    background: float
    noise_rms: float
    status: str  # "source_measured" or "no_source_detected"
    source: dict[str, Any] | None
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "input_sha256": self.input_sha256,
            "width": self.width,
            "height": self.height,
            "n_masked": self.n_masked,
            "background": self.background,
            "noise_rms": self.noise_rms,
            "status": self.status,
            "source": self.source,
            "caveats": self.caveats,
            "disclaimer": DISCLAIMER,
        }


def _validate(a: Any) -> tuple[F64, int]:
    try:
        img = np.asarray(a, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise InvalidImage("the image must be a numeric 2-D array") from exc
    if img.ndim != 2:
        raise InvalidImage("the image must be two-dimensional (one band)")
    h, w = img.shape
    if min(h, w) < MIN_SIDE:
        raise InvalidImage(f"the image is too small; each side must be at least {MIN_SIDE} pixels")
    if max(h, w) > MAX_SIDE:
        raise InvalidImage(f"the image is too large; each side must be at most {MAX_SIDE} pixels")
    bad = ~np.isfinite(img)
    if bad.mean() > 0.2:
        raise InvalidImage("more than 20 percent of the pixels are not finite")
    return img, int(bad.sum())


def _background(img: F64, bad: npt.NDArray[np.bool_]) -> tuple[float, float]:
    """Iterative 3-sigma clipped median and a MAD-based noise estimate."""
    v = img[~bad]
    for _ in range(6):
        med = float(np.median(v))
        sig = 1.4826 * float(np.median(np.abs(v - med)))
        if sig <= 0:
            break
        keep = np.abs(v - med) < 3.0 * sig
        if keep.all():
            break
        v = v[keep]
    med = float(np.median(v))
    sig = 1.4826 * float(np.median(np.abs(v - med)))
    if not sig > 0:
        raise InvalidImage("the image is flat: its noise level is zero, so nothing can be measured")
    return med, sig


def _box3(x: F64) -> F64:
    p = np.pad(x, 1, mode="edge")
    return np.asarray(
        sum(p[i : i + x.shape[0], j : j + x.shape[1]] for i in range(3) for j in range(3)) / 9.0
    )


def _component(mask: npt.NDArray[np.bool_], seed: tuple[int, int]) -> npt.NDArray[np.bool_]:
    """Pixels of `mask` 4-connected to `seed` (repeated dilation, no SciPy needed)."""
    cur = np.zeros_like(mask)
    cur[seed] = True
    while True:
        p = np.pad(cur, 1)
        grown = (cur | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]) & mask
        if (grown == cur).all():
            return cur
        cur = grown


def _enclosed_radii(r: F64, f: F64, total: float, fractions: tuple[float, ...]) -> list[float]:
    order = np.argsort(r, kind="stable")
    cum = np.cumsum(f[order])
    rs = r[order]
    out = []
    for q in fractions:
        k = int(np.searchsorted(cum, q * total))
        out.append(float(rs[min(k, len(rs) - 1)]))
    return out


def analyze_image(data: Any) -> ImageAnalysis:
    img, n_bad = _validate(data)
    bad = ~np.isfinite(img)
    sha = hashlib.sha256(np.ascontiguousarray(np.where(bad, 0.0, img)).tobytes()).hexdigest()
    bkg, rms = _background(img, bad)
    clean = np.where(bad, bkg, img)
    sub = clean - bkg
    h, w = sub.shape
    caveats = [
        "Descriptors depend on resolution, depth and how the cutout was made. "
        "Compare images only when they were "
        "made the same way.",
        "No morphological class and no redshift is assigned.",
        "Asymmetry has the expected noise contribution removed; very faint sources "
        "can still read as asymmetric.",
    ]
    if n_bad:
        caveats.append(f"{n_bad} non-finite pixels were replaced by the background level.")
    sm = _box3(sub)
    mask = sm > 3.0 * rms / 3.0  # 3 sigma on the 3x3 mean, whose noise is rms / 3
    if not mask.any():
        return ImageAnalysis(sha, w, h, n_bad, bkg, rms, "no_source_detected", None, caveats)
    peak = np.unravel_index(int(np.argmax(np.where(mask, sm, -np.inf))), sm.shape)
    comp = _component(mask, (int(peak[0]), int(peak[1])))
    npix = int(comp.sum())
    if npix < MIN_SOURCE_PIXELS:
        return ImageAnalysis(sha, w, h, n_bad, bkg, rms, "no_source_detected", None, caveats)
    yy, xx = np.indices(sub.shape)
    wt = np.where(comp, np.clip(sub, 0, None), 0.0)
    flux_c = float(wt.sum())
    cx, cy = float((wt * xx).sum() / flux_c), float((wt * yy).sum() / flux_c)
    snr = float(sub[comp].sum() / (rms * np.sqrt(npix)))
    rr = np.hypot(xx - cx, yy - cy)
    r_comp = float(rr[comp].max())
    r_edge = float(min(cx, cy, w - 1 - cx, h - 1 - cy))
    big_r = max(2.0, min(1.5 * r_comp + 2.0, r_edge))
    ap = rr <= big_r
    f_ap = np.clip(sub[ap], 0, None)
    total = float(f_ap.sum())
    if total <= 0:
        return ImageAnalysis(sha, w, h, n_bad, bkg, rms, "no_source_detected", None, caveats)
    r20, r50, r80 = _enclosed_radii(rr[ap], f_ap, total, (0.2, 0.5, 0.8))
    conc = float(5.0 * np.log10(max(r80, 0.5) / max(r20, 0.5)))
    # rotational asymmetry about the centroid, within radius big_r
    ix, iy = int(round(cx)), int(round(cy))
    half = int(min(big_r, ix, iy, w - 1 - ix, h - 1 - iy))
    patch = sub[iy - half : iy + half + 1, ix - half : ix + half + 1]
    py, px = np.indices(patch.shape)
    inside = np.hypot(px - half, py - half) <= half
    diff = np.abs(patch - patch[::-1, ::-1])[inside].sum()
    denom = float(np.abs(patch[inside]).sum())
    a_noise = float(inside.sum() * 2.0 * rms / np.sqrt(np.pi) / denom) if denom > 0 else 0.0
    asym = float(max(0.0, diff / denom - a_noise)) if denom > 0 else 0.0
    # shape from flux-weighted second moments of the detected region
    dx, dy = xx - cx, yy - cy
    mxx = float((wt * dx * dx).sum() / flux_c)
    myy = float((wt * dy * dy).sum() / flux_c)
    mxy = float((wt * dx * dy).sum() / flux_c)
    tr, det = mxx + myy, mxx * myy - mxy * mxy
    disc = np.sqrt(max(tr * tr / 4.0 - det, 0.0))
    a_ax, b_ax = np.sqrt(max(tr / 2.0 + disc, 1e-12)), np.sqrt(max(tr / 2.0 - disc, 1e-12))
    ell = float(1.0 - b_ax / a_ax)
    pa = float(np.degrees(0.5 * np.arctan2(2.0 * mxy, mxx - myy)) % 180.0)
    if r20 < 1.0:
        caveats.append(
            "The core is not resolved at this pixel scale, so the concentration is a lower limit "
            "and r20 is not a measurement."
        )
    if r_edge < 1.5 * r_comp:
        caveats.append(
            "The source reaches close to the image edge, so its light is partly cut off."
        )
    source = {
        "centroid_xy": [cx, cy],
        "n_pixels": npix,
        "snr": snr,
        "flux": total,
        "r20_px": r20,
        "r50_px": r50,
        "r80_px": r80,
        "concentration": conc,
        "asymmetry": asym,
        "ellipticity": ell,
        "position_angle_deg": pa,
        "aperture_radius_px": big_r,
    }
    return ImageAnalysis(sha, w, h, n_bad, bkg, rms, "source_measured", source, caveats)


def downsample_for_preview(data: Any, side: int = PREVIEW_SIDE) -> dict[str, Any]:
    """Block-mean downsample to at most `side` pixels and return float32 little-endian base64."""
    img, _ = _validate(data)
    img = np.where(np.isfinite(img), img, np.nan)
    h, w = img.shape
    k = int(np.ceil(max(h, w) / side))
    hh, ww = (h // k) * k, (w // k) * k
    with np.errstate(all="ignore"):
        small = (
            np.nanmean(img[:hh, :ww].reshape(hh // k, k, ww // k, k), axis=(1, 3)) if k > 1 else img
        )
    fin = small[np.isfinite(small)]
    lo, hi = (
        (float(np.percentile(fin, 0.5)), float(np.percentile(fin, 99.9)))
        if fin.size
        else (0.0, 1.0)
    )
    pix = np.nan_to_num(small, nan=float(np.median(fin)) if fin.size else 0.0).astype("<f4")
    return {
        "width": int(pix.shape[1]),
        "height": int(pix.shape[0]),
        "factor": k,
        "pixels_b64": base64.b64encode(pix.tobytes()).decode("ascii"),
        "vmin": lo,
        "vmax": hi,
    }


def read_fits_bytes(raw: bytes) -> F64:
    """First 2-D image HDU of an uncompressed FITS file. Sizes are checked from the header before
    any pixel data is read, and only plain image HDUs are accepted."""
    from astropy.io import fits

    try:
        with fits.open(io.BytesIO(raw), memmap=False, ignore_missing_end=False) as hdul:
            for hdu in hdul:
                if type(hdu).__name__ not in ("PrimaryHDU", "ImageHDU"):
                    continue
                naxis = int(hdu.header.get("NAXIS", 0))
                if naxis != 2:
                    continue
                n1, n2 = int(hdu.header["NAXIS1"]), int(hdu.header["NAXIS2"])
                if n1 > MAX_SIDE or n2 > MAX_SIDE:
                    raise InvalidImage(
                        f"the FITS image is {n1} by {n2}; each side must be at most {MAX_SIDE}"
                    )
                return np.asarray(hdu.data, dtype=np.float64)
    except InvalidImage:
        raise
    except Exception as exc:  # noqa: BLE001  (astropy raises many types for malformed files)
        raise InvalidImage("could not read the file as FITS") from exc
    raise InvalidImage("no plain two-dimensional image was found in the FITS file")
