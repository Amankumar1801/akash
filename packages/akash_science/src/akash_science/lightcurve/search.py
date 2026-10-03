"""Transit search via Box Least Squares (astropy), iterated with in-transit masking."""

from __future__ import annotations

from typing import Any

import numpy as np
from astropy.timeseries import BoxLeastSquares

from ..config import SearchConfig
from .types import F64, TCE


def in_transit_mask(time: F64, period: float, t0: float, width: float) -> np.ndarray:
    dt = (time - t0 + 0.5 * period) % period - 0.5 * period
    return np.abs(dt) <= 0.5 * width


def red_noise_beta(time: F64, resid: F64, duration: float, sigma: float,
                   exclude: np.ndarray) -> float:
    """Pont et al. (2006)-style beta >= 1: measured scatter of duration-sized bin means over
    the white-noise expectation. SNR is divided by beta so correlated noise can't fake a signal."""
    keep = ~exclude
    t, r = time[keep], resid[keep]
    if len(t) < 50 or sigma <= 0 or duration <= 0:
        return 1.0
    b = np.floor((t - t[0]) / duration).astype(np.int64)
    uniq, inv, cnt = np.unique(b, return_inverse=True, return_counts=True)
    sel = cnt >= 3
    if sel.sum() < 8:
        return 1.0
    sums = np.bincount(inv, weights=r)
    means = (sums / cnt)[sel]
    expected = sigma / np.sqrt(cnt[sel].mean())
    measured = 1.4826 * np.median(np.abs(means - np.median(means)))
    return float(max(1.0, measured / expected))


class BLSSearcher:
    def __init__(self, cfg: SearchConfig) -> None:
        self.cfg = cfg
        self.last_stats: list[dict[str, Any]] = []  # compute_stats per returned TCE, same order

    def _periods(self, bls: BoxLeastSquares, durations: F64, max_p: float) -> F64:
        cfg, ff = self.cfg, self.cfg.frequency_factor
        periods = bls.autoperiod(durations, minimum_period=cfg.min_period_days,
                                 maximum_period=max_p, frequency_factor=ff)
        while len(periods) > cfg.max_periods:  # keep runtime bounded on long baselines
            ff *= 1.5
            periods = bls.autoperiod(durations, minimum_period=cfg.min_period_days,
                                     maximum_period=max_p, frequency_factor=ff)
        return np.asarray(periods)

    def _beta(self, trel: F64, flux: F64, sigma: float, period: float, t0: float,
              dur: float) -> float:
        if not self.cfg.correct_red_noise:
            return 1.0
        excl = in_transit_mask(trel, period, t0, 2.0 * dur)
        return red_noise_beta(trel, flux - 1.0, dur, sigma, excl)

    def search(self, time: F64, flux: F64, sigma: float) -> list[TCE]:
        cfg = self.cfg
        self.last_stats = []
        if len(time) < 100 or sigma <= 0:
            return []
        baseline = float(time[-1] - time[0])
        max_p = cfg.max_period_days or baseline / cfg.min_transits
        durations = np.array([d for d in cfg.durations_days if d < cfg.min_period_days])
        if durations.size == 0:
            return []
        t_ref = float(time[0])
        trel = time - t_ref
        avail = np.ones(len(time), dtype=bool)
        tces: list[TCE] = []
        cadence = float(np.median(np.diff(trel)))

        for rank in range(1, cfg.max_tces + 1):
            if avail.sum() < 100:
                break
            bls = BoxLeastSquares(trel[avail], flux[avail], dy=np.full(avail.sum(), sigma))
            res = bls.power(self._periods(bls, durations, max_p), durations,
                            objective="likelihood")
            valid = (np.asarray(res.duration) / np.asarray(res.period)) <= cfg.max_duty_cycle
            if not valid.any():
                break
            i = int(np.argmax(np.where(valid, res.power, -np.inf)))
            p0, d0, t00 = float(res.period[i]), float(res.duration[i]), float(res.transit_time[i])
            sde = float((res.power[i] - np.mean(res.power)) / (np.std(res.power) or 1.0))
            # cheap pre-gate on the coarse peak (deflated by beta), generous so refinement can
            # still lift a borderline peak over threshold
            beta0 = self._beta(trel, flux, sigma, p0, t00, d0)
            snr0 = float(res.depth_snr[i]) / beta0
            if not np.isfinite(snr0) or snr0 < 0.8 * cfg.snr_threshold or res.depth[i] <= 0:
                break

            period, dur, t0, fine, pw = self._refine(bls, p0, d0)
            fr = bls.power(np.array([period]), np.array([dur]), objective="likelihood")
            depth = float(fr.depth[0])
            beta = self._beta(trel, flux, sigma, period, t0, dur)
            snr = float(fr.depth_snr[0]) / beta  # FINAL SNR always carries the red-noise guard
            if not np.isfinite(snr) or snr < cfg.snr_threshold or depth <= 0:
                break
            lo, hi = self._interval(fine, pw, period, beta)

            stats = bls.compute_stats(period, dur, t0)
            expected = max(dur / cadence, 1.0)
            counts = np.asarray(stats["per_transit_count"])
            good = counts >= 0.5 * expected
            tt = [float(x) + t_ref for x, g in zip(stats["transit_times"], good, strict=True) if g]
            if int(good.sum()) >= cfg.min_transits:
                tces.append(TCE(rank=rank, period_d=period, period_interval_d=(lo, hi),
                                t0_bjd=t0 + t_ref, duration_d=dur, depth_frac=depth, snr=snr,
                                sde=sde, n_transits=int(good.sum()), transit_times_bjd=tt,
                                beta=beta))
                self.last_stats.append(stats)
            avail &= ~in_transit_mask(trel, period, t0, cfg.mask_factor * dur * 2.0)
        return tces

    @staticmethod
    def _refine(bls: BoxLeastSquares, p: float, dur: float
                ) -> tuple[float, float, float, F64, F64]:
        """Fine grid around the coarse peak over (P, duration). The coarse BLS grid is too
        coarse: a 0.03% period error slides the fold by ~25% of a transit over 8 cycles."""
        fine = np.linspace(p * 0.995, p * 1.005, 801)
        durs = np.linspace(0.7 * dur, 1.4 * dur, 12)
        r = bls.power(fine, durs, objective="likelihood", oversample=20)
        pw = np.asarray(r.power)
        k = int(np.argmax(pw))
        return float(r.period[k]), float(r.duration[k]), float(r.transit_time[k]), \
            np.asarray(r.period, dtype=np.float64), pw

    @staticmethod
    def _interval(fine: F64, pw: F64, p: float, beta: float) -> tuple[float, float]:
        """Approx period interval: region around the peak with logL >= max - 0.5*beta^2.
        Heuristic, NOT a calibrated confidence interval (coverage is unmeasured)."""
        k = int(np.argmin(np.abs(fine - p)))
        ok = pw >= pw[k] - 0.5 * beta**2
        a = k
        while a > 0 and ok[a - 1]:
            a -= 1
        b = k
        while b < len(ok) - 1 and ok[b + 1]:
            b += 1
        step = float(fine[1] - fine[0])
        return float(fine[a]) - step / 2, float(fine[b]) + step / 2
