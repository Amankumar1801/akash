"""Stochastic-variability descriptors: excess variance, structure function, damped-random-walk fit.

These are standard descriptors of accretion-driven variability, but this module
does not classify an object as an AGN. Instrument systematics, eclipses, flares and starspots all
produce variability too, and the damping timescale needs a baseline many times longer than itself,
which a single TESS sector (about 27 days) rarely provides. The output says when that is the case.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
from astropy.timeseries import LombScargle

F64 = npt.NDArray[np.float64]
MIN_POINTS = 60
MAX_SF_POINTS = 2000
N_BINS = 12
MIN_PAIRS = 30
CHARACTERS = (
    "insufficient_data",
    "no_significant_variability",
    "periodic_like",
    "stochastic_aperiodic",
)
CAVEATS = [
    "This describes how the brightness varies. It does not say what kind of object varies.",
    "Systematics, eclipses, flares and spots also produce variability.",
    "The structure-function bin errors are not computed; neighbouring pairs are not independent.",
]


def _insufficient(reason: str, n: int = 0) -> dict[str, Any]:
    return {"character": "insufficient_data", "reason": reason, "n_points": n, "caveats": CAVEATS}


def _excess_variance(x: F64, e: F64) -> dict[str, Any]:
    """Normalised excess variance and F_var (Vaughan et al. 2003); x has unit mean."""
    n = len(x)
    s2 = float(np.var(x, ddof=1))
    me2 = float(np.mean(e**2))
    nxs = s2 - me2
    fvar = float(np.sqrt(nxs)) if nxs > 0 else 0.0
    err = float(np.sqrt((np.sqrt(2.0 / n) * me2) ** 2 + (np.sqrt(me2 / n) * 2.0 * fvar) ** 2))
    return {
        "nxs": nxs,
        "nxs_err": err,
        "fvar": fvar,
        "significant": bool(nxs > 3.0 * err and nxs > 0),
    }


def _structure_function(t: F64, x: F64, e: F64, cadence: float, baseline: float) -> dict[str, Any]:
    step = max(1, int(np.ceil(len(t) / MAX_SF_POINTS)))
    t, x, e = t[::step], x[::step], e[::step]
    i, j = np.triu_indices(len(t), 1)
    dt = t[j] - t[i]
    d2 = (x[j] - x[i]) ** 2 - (e[i] ** 2 + e[j] ** 2)
    lo, hi = 2.0 * cadence * step, baseline / 2.0
    if hi <= lo * 2:
        return {"bins": [], "slope": None, "n_bins_used": 0}
    edges = np.geomspace(lo, hi, N_BINS + 1)
    bins: list[dict[str, float]] = []
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        m = (dt >= a) & (dt < b)
        if int(m.sum()) >= MIN_PAIRS:
            bins.append(
                {
                    "tau_d": float(np.sqrt(a * b)),
                    "sf2": float(np.mean(d2[m])),
                    "n_pairs": int(m.sum()),
                }
            )
    use = [b for b in bins if b["sf2"] > 0]
    slope = None
    if len(use) >= 4:
        lt = np.log10([b["tau_d"] for b in use])
        ls = np.log10([b["sf2"] for b in use])
        slope = float(np.polyfit(lt, ls, 1)[0] / 2.0)  # SF = sqrt(SF^2) ~ tau^slope
    return {"bins": bins, "slope": slope, "n_bins_used": len(use), "subsample_step": step}


def _drw(sf: dict[str, Any], cadence: float, baseline: float) -> dict[str, Any] | None:
    bins = [b for b in sf["bins"] if b["sf2"] > 0]
    if len(bins) < 4:
        return None
    tau = np.array([b["tau_d"] for b in bins])
    y = np.array([b["sf2"] for b in bins])
    wts = 1.0 / y**2  # relative errors
    best: tuple[float, float, float] | None = None
    for td_i in np.geomspace(2.0 * cadence, 10.0 * baseline, 80):
        m = 2.0 * (1.0 - np.exp(-tau / td_i))
        sig2 = float(np.sum(wts * m * y) / np.sum(wts * m * m))
        chi = float(np.sum(wts * (y - sig2 * m) ** 2))
        if best is None or chi < best[0]:
            best = (chi, float(td_i), sig2)
    assert best is not None
    _, td, sig2 = best
    reliable = bool(baseline >= 10.0 * td and td >= 2.0 * cadence)
    return {
        "tau_d_days": td,
        "sigma_frac": float(np.sqrt(max(sig2, 0.0))),
        "tau_d_reliable": reliable,
        "note": None
        if reliable
        else "The baseline is under ten times this damping timescale, so the timescale is "
            "not constrained. "
        "Treat it as a rough scale, not a measurement.",
    }


def _periodicity(t: F64, x: F64, e: F64, cadence: float, baseline: float) -> dict[str, Any]:
    """Peak-over-red-noise test (Vaughan 2005). A white-noise false-alarm probability would call
    ordinary red noise periodic, because red noise puts its power at the lowest frequencies."""
    step = max(1, int(np.ceil(len(t) / MAX_SF_POINTS)))
    ts, xs, es = t[::step], x[::step], e[::step]
    spp = 5
    freq, power = LombScargle(ts, xs, es).autopower(
        minimum_frequency=1.0 / baseline,
        maximum_frequency=1.0 / (4.0 * cadence * step),
        samples_per_peak=spp,
    )
    ok = np.isfinite(power) & (power > 0)
    if int(ok.sum()) < 8:
        return {
            "best_period_d": None,
            "peak_ratio": None,
            "threshold_ratio": None,
            "n_cycles": None,
            "noise_slope": None,
            "periodic": False,
        }
    slope, icpt = np.polyfit(np.log(freq[ok]), np.log(power[ok]), 1)
    model = np.exp(
        icpt + slope * np.log(freq) + 0.5772
    )  # ln of a chi2(2)/2 variate has mean -0.5772
    ratio = power / model
    k = int(np.argmax(ratio))
    # Deliberately strict (1e-5 over the band): the power-law continuum only
    # approximates a bending PSD.
    threshold = float(np.log(max(len(freq) / spp, 2.0) / 1e-5))
    period = float(1.0 / freq[k])
    return {
        "best_period_d": period,
        "peak_ratio": float(ratio[k]),
        "threshold_ratio": threshold,
        "n_cycles": float(baseline / period),
        "noise_slope": float(slope),
        "periodic": bool(ratio[k] > threshold and baseline / period >= 5.0),
    }


def analyze_variability(time: Any, flux: Any, flux_err: Any = None) -> dict[str, Any]:
    try:
        t = np.asarray(time, dtype=np.float64)
        f = np.asarray(flux, dtype=np.float64)
        e = None if flux_err is None else np.asarray(flux_err, dtype=np.float64)
    except (TypeError, ValueError):
        return _insufficient("time and flux must be numeric")
    if t.ndim != 1 or t.shape != f.shape or (e is not None and e.shape != t.shape):
        return _insufficient("time, flux and flux_err must be one-dimensional and equal length")
    ok = np.isfinite(t) & np.isfinite(f) & (True if e is None else np.isfinite(e))
    t, f = t[ok], f[ok]
    e = None if e is None else e[ok]
    if len(t) < MIN_POINTS:
        return _insufficient(f"need at least {MIN_POINTS} finite points", len(t))
    order = np.argsort(t, kind="stable")
    t, f = t[order], f[order]
    e = None if e is None else e[order]
    keep = np.append(True, np.diff(t) > 0)
    t, f = t[keep], f[keep]
    e = None if e is None else e[keep]
    mean = float(np.mean(f))
    if mean <= 0:
        return _insufficient("mean flux must be positive", len(t))
    x = f / mean
    if e is not None and (e > 0).all():
        err, source = e / mean, "flux_err"
    else:
        err = np.full_like(
            x, float(np.median(np.abs(np.diff(x) - np.median(np.diff(x)))) * 1.4826 / np.sqrt(2))
        )
        source = "point_to_point"
    cadence = float(np.median(np.diff(t)))
    baseline = float(t[-1] - t[0])
    if baseline < 20.0 * cadence:
        return _insufficient(
            "the baseline is too short compared with the sampling interval", len(t)
        )
    ev = _excess_variance(x, err)
    sf = _structure_function(t, x, err, cadence, baseline)
    out: dict[str, Any] = {
        "n_points": len(t),
        "baseline_days": baseline,
        "median_cadence_days": cadence,
        "error_source": source,
        "excess_variance": ev,
        "structure_function": sf,
        "damped_random_walk": None,
        "periodicity": None,
        "caveats": CAVEATS,
        "reason": None,
    }
    if not ev["significant"]:
        out["character"] = "no_significant_variability"
        return out
    out["periodicity"] = _periodicity(t, x, err, cadence, baseline)
    out["damped_random_walk"] = _drw(sf, cadence, baseline)
    out["character"] = "periodic_like" if out["periodicity"]["periodic"] else "stochastic_aperiodic"
    return out
