"""Vetting checks v1. Each check is independent -> PASS / WARN / FAIL / UNKNOWN.

Thresholds are module constants chosen for transparency, NOT calibrated against Robovetter/DV;
their effect is to be measured in Phase 10. Results are never averaged into one number.
Errors on depths use sigma * beta (beta = red-noise inflation carried on the TCE).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from akash_core.enums import VetStatus

from .types import F64, VetContext, VetResult

ODD_EVEN_WARN_SIGMA, ODD_EVEN_FAIL_SIGMA = 3.0, 5.0
SECONDARY_WARN_SIGMA, SECONDARY_FAIL_RATIO = 3.0, 0.5
V_SHAPE_MIN_INGRESS, V_SHAPE_MIN_DELTA_CHI2 = 0.4, 4.0
DEPTH_CONSISTENCY_WARN_CHI2 = 3.0
SYSTEMATIC_FRACTION_WARN = 0.5
EDGE_DISTANCE_D = 0.25
DURATION_RATIO_WARN = (0.1, 1.3)
DURATION_RATIO_FAIL_HI = 1.8
RJUP_PER_RSUN = 0.10045
MAX_PLANET_RJUP = 2.0
MIN_PTS = 5


def _phase(ctx: VetContext) -> F64:
    p = ctx.tce.period_d
    return np.asarray((ctx.time - ctx.tce.t0_bjd + 0.5 * p) % p - 0.5 * p, dtype=np.float64)


def _depth_err(ctx: VetContext, n: int) -> float:
    return ctx.sigma * ctx.tce.beta / math.sqrt(max(n, 1))


class OddEvenCheck:
    name = "odd_even"

    def run(self, ctx: VetContext) -> VetResult:
        tce, t, f = ctx.tce, ctx.time, ctx.flux
        inn = np.abs(_phase(ctx)) <= 0.5 * tce.duration_d
        epoch = np.round((t - tce.t0_bjd) / tce.period_d).astype(int)
        odd, even = inn & (epoch % 2 == 1), inn & (epoch % 2 == 0)
        if tce.n_transits < 4 or odd.sum() < MIN_PTS or even.sum() < MIN_PTS:
            return VetResult(self.name, VetStatus.UNKNOWN, "need >=2 odd and >=2 even transits")
        do, de = 1 - float(f[odd].mean()), 1 - float(f[even].mean())
        eo, ee = _depth_err(ctx, int(odd.sum())), _depth_err(ctx, int(even.sum()))
        sig = abs(do - de) / math.hypot(eo, ee)
        m = {"depth_odd_ppm": do * 1e6, "depth_even_ppm": de * 1e6, "sigma": sig}
        if sig >= ODD_EVEN_FAIL_SIGMA:
            return VetResult(self.name, VetStatus.FAIL,
                             f"odd/even depths differ at {sig:.1f} sigma (EB-like)", m)
        if sig >= ODD_EVEN_WARN_SIGMA:
            return VetResult(self.name, VetStatus.WARN, f"odd/even tension {sig:.1f} sigma", m)
        return VetResult(self.name, VetStatus.PASS, f"odd/even consistent ({sig:.1f} sigma)", m)


class SecondaryEclipseCheck:
    name = "secondary_eclipse"

    def run(self, ctx: VetContext) -> VetResult:
        tce = ctx.tce
        ph = (ctx.time - tce.t0_bjd) % tce.period_d - 0.5 * tce.period_d  # 0 at phase 0.5
        sel = np.abs(ph) <= 0.5 * tce.duration_d
        if sel.sum() < MIN_PTS:
            return VetResult(self.name, VetStatus.UNKNOWN, "no coverage at phase 0.5")
        d = 1 - float(ctx.flux[sel].mean())
        sig = d / _depth_err(ctx, int(sel.sum()))
        m = {"secondary_depth_ppm": d * 1e6, "secondary_sigma": sig,
             "ratio_to_primary": d / tce.depth_frac}
        if sig >= SECONDARY_WARN_SIGMA and d / tce.depth_frac >= SECONDARY_FAIL_RATIO:
            return VetResult(self.name, VetStatus.FAIL,
                             "secondary comparable to primary (likely EB at 2x period)", m)
        if sig >= SECONDARY_WARN_SIGMA:
            return VetResult(self.name, VetStatus.WARN,
                             f"possible secondary at phase 0.5 ({sig:.1f} sigma)", m)
        return VetResult(self.name, VetStatus.PASS,
                         f"no significant secondary ({sig:.1f} sigma)", m)


def _trap_shape(dt: F64, t14: float, ingress_frac: float) -> F64:
    ing = max(ingress_frac * t14, 1e-9)
    return np.asarray(np.clip((0.5 * t14 - np.abs(dt)) / ing, 0.0, 1.0), dtype=np.float64)


class TransitShapeCheck:
    """Chi-square comparison of trapezoids over a (T14, ingress-fraction) grid.
    f~0.5 is a V/triangle (grazing or stellar-companion-like); small f is flat-bottomed."""

    name = "transit_shape"
    FRACS = (0.05, 0.1, 0.2, 0.3, 0.4, 0.5)
    SCALES = (0.8, 0.9, 1.0, 1.1, 1.25, 1.5)

    def run(self, ctx: VetContext) -> VetResult:
        ph = _phase(ctx)
        dur = ctx.tce.duration_d
        sel = np.abs(ph) <= 2.0 * dur
        if (np.abs(ph) <= 0.5 * dur).sum() < 8:
            return VetResult(self.name, VetStatus.UNKNOWN, "too few in-transit points")
        x, y = ph[sel], 1.0 - ctx.flux[sel]
        err = ctx.sigma * ctx.tce.beta
        best: dict[float, float] = {}
        for fr in self.FRACS:
            chis = []
            for sc in self.SCALES:
                s = _trap_shape(x, dur * sc, fr)
                den = float((s * s).sum())
                if den <= 0:
                    continue
                a = max(float((y * s).sum()) / den, 0.0)
                chis.append(float((((y - a * s) / err) ** 2).sum()))
            if chis:
                best[fr] = min(chis)
        if not best:
            return VetResult(self.name, VetStatus.UNKNOWN, "model fit failed")
        f_best = min(best, key=lambda k: best[k])
        flat = min(v for k, v in best.items() if k <= 0.2)
        vee = min(v for k, v in best.items() if k >= V_SHAPE_MIN_INGRESS)
        delta = flat - vee
        m = {"best_ingress_fraction": f_best, "delta_chi2_flat_minus_v": delta}
        if f_best >= V_SHAPE_MIN_INGRESS and delta >= V_SHAPE_MIN_DELTA_CHI2:
            return VetResult(self.name, VetStatus.WARN,
                             "V-shaped dip (grazing/stellar-companion-like)", m)
        return VetResult(self.name, VetStatus.PASS, "flat-bottomed dip preferred", m)


class PeriodicityCoverageCheck:
    name = "periodicity_coverage"

    def run(self, ctx: VetContext) -> VetResult:
        tce = ctx.tce
        if tce.n_transits < 2:
            return VetResult(self.name, VetStatus.WARN, "single transit: period unverified",
                             {"n_transits": float(tce.n_transits)})
        d, e = [], []
        for tt in tce.transit_times_bjd:
            inn = np.abs(ctx.time - tt) <= 0.5 * tce.duration_d
            if inn.sum() >= 3:
                d.append(1 - float(ctx.flux[inn].mean()))
                e.append(_depth_err(ctx, int(inn.sum())))
        if len(d) < 2:
            return VetResult(self.name, VetStatus.UNKNOWN, "too few covered transits")
        da, ea = np.array(d), np.array(e)
        w = 1 / ea**2
        mean = float((w * da).sum() / w.sum())
        chi2 = float((((da - mean) / ea) ** 2).sum() / (len(da) - 1))
        m = {"n_transits": float(tce.n_transits), "reduced_chi2_individual_depths": chi2}
        if chi2 >= DEPTH_CONSISTENCY_WARN_CHI2:
            return VetResult(self.name, VetStatus.WARN,
                             f"individual transit depths inconsistent (chi2_red={chi2:.1f})", m)
        return VetResult(self.name, VetStatus.PASS,
                         f"{tce.n_transits} transits, consistent depths (chi2_red={chi2:.1f})", m)


class SystematicsCoincidenceCheck:
    """Do transits coincide with cadences dropped for quality flags, or sit at segment edges?"""

    name = "systematics_coincidence"

    def run(self, ctx: VetContext) -> VetResult:
        tce = ctx.tce
        tts = tce.transit_times_bjd
        if not tts:
            return VetResult(self.name, VetStatus.UNKNOWN, "no transit times")
        half = 0.5 * tce.duration_d
        ft = ctx.flagged_time
        n_flag = sum(1 for tt in tts if len(ft) and bool(np.any(np.abs(ft - tt) <= half)))
        n_edge = sum(1 for tt in tts if any(
            min(abs(tt - a), abs(tt - b)) <= EDGE_DISTANCE_D for a, b in ctx.segment_edges))
        fo, fe = n_flag / len(tts), n_edge / len(tts)
        m = {"frac_overlap_flagged": fo, "frac_near_segment_edge": fe}
        if fo >= SYSTEMATIC_FRACTION_WARN or fe >= SYSTEMATIC_FRACTION_WARN:
            return VetResult(self.name, VetStatus.WARN,
                             "many transits coincide with flagged cadences or segment edges", m)
        return VetResult(self.name, VetStatus.PASS,
                         "transits not dominated by flagged cadences/edges", m)


class DurationPlausibilityCheck:
    name = "duration_plausibility"

    def run(self, ctx: VetContext) -> VetResult:
        rho = None if ctx.stellar is None else ctx.stellar.density_solar
        if rho is None or rho <= 0:
            return VetResult(self.name, VetStatus.UNKNOWN, "no stellar density")
        t_exp = (13.0 / 24.0) * (ctx.tce.period_d / 365.25) ** (1 / 3) * rho ** (-1 / 3)
        ratio = ctx.tce.duration_d / t_exp
        m = {"observed_over_expected": ratio, "expected_hours": t_exp * 24.0}
        if ratio >= DURATION_RATIO_FAIL_HI:
            return VetResult(self.name, VetStatus.FAIL,
                             f"duration {ratio:.1f}x a central transit of this star", m)
        lo, hi = DURATION_RATIO_WARN
        if ratio > hi or ratio < lo:
            return VetResult(self.name, VetStatus.WARN,
                             f"duration ratio {ratio:.2f} outside typical range", m)
        return VetResult(self.name, VetStatus.PASS, f"duration ratio {ratio:.2f}", m)


class DepthRadiusCheck:
    name = "depth_radius"

    def run(self, ctx: VetContext) -> VetResult:
        s = ctx.stellar
        if s is None or s.radius_rsun is None:
            return VetResult(self.name, VetStatus.UNKNOWN, "no stellar radius")
        rp = math.sqrt(max(ctx.tce.depth_frac, 0.0)) * s.radius_rsun / RJUP_PER_RSUN
        m = {"implied_radius_rjup": rp}
        if rp > MAX_PLANET_RJUP:
            return VetResult(self.name, VetStatus.WARN,
                             f"implied radius {rp:.1f} R_Jup too large for a planet", m)
        return VetResult(self.name, VetStatus.PASS, f"implied radius {rp:.2f} R_Jup", m)


DEFAULT_CHECKS: tuple[OddEvenCheck | SecondaryEclipseCheck | TransitShapeCheck
                      | PeriodicityCoverageCheck | SystematicsCoincidenceCheck
                      | DurationPlausibilityCheck | DepthRadiusCheck, ...] = (
    OddEvenCheck(), SecondaryEclipseCheck(), TransitShapeCheck(), PeriodicityCoverageCheck(),
    SystematicsCoincidenceCheck(), DurationPlausibilityCheck(), DepthRadiusCheck())


def run_checks(ctx: VetContext, checks: Sequence[object] = DEFAULT_CHECKS) -> list[VetResult]:
    """A crashing check degrades to UNKNOWN; it never aborts the investigation."""
    out: list[VetResult] = []
    for c in checks:
        try:
            out.append(c.run(ctx))  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001  (intentional: isolate faulty checks)
            out.append(VetResult(getattr(c, "name", "unknown"), VetStatus.UNKNOWN,
                                 f"check raised {type(e).__name__}: {e}"))
    return out
