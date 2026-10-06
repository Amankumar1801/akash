"""Gaia stellar enrichment: parameters for vetting, RUWE (binarity), and a nearby-source
contamination assessment.

Contamination logic (conservative, documented): a neighbour inside the photometric aperture could
be the true source of an observed dip if, even if it eclipsed completely, its flux fraction of the
aperture total is >= the observed depth. Gaia G is used as a proxy for the survey bandpass, and
all neighbour flux is assumed to fall in the aperture (no PSF weighting), which overstates
contamination, i.e. errs toward flagging."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol

from akash_core.schemas import AstronomicalObject
from akash_data.base import CatalogRecord
from akash_science.lightcurve.types import StellarContext

TESS_PIXEL_ARCSEC = 21.0
RUWE_BINARITY_SUSPECT = 1.4  # Gaia documentation's customary threshold


class GaiaLike(Protocol):
    last_query: str

    def lookup(self, obj: AstronomicalObject) -> list[CatalogRecord]: ...
    def cone_for_object_epoch(
        self, ra: float, dec: float, pmra: float | None, pmdec: float | None, epoch: float,
        radius_arcsec: float) -> tuple[list[dict[str, Any]], tuple[float, float]]: ...


@dataclass(frozen=True)
class Neighbor:
    source_id: str
    sep_arcsec: float
    g_mag: float | None
    delta_g: float | None  # neighbour minus target (positive = fainter)


@dataclass
class StellarProfile:
    source_id: str | None
    g_mag: float | None
    teff: float | None
    logg: float | None
    radius_rsun: float | None
    ruwe: float | None
    neighbors: list[Neighbor] = field(default_factory=list)
    star_record: CatalogRecord | None = None
    cone_record: CatalogRecord | None = None

    def context(self) -> StellarContext:
        return StellarContext(radius_rsun=self.radius_rsun, logg=self.logg)

    @property
    def binarity_suspect(self) -> bool | None:
        return None if self.ruwe is None else self.ruwe > RUWE_BINARITY_SUSPECT


@dataclass(frozen=True)
class ContaminationAssessment:
    capable: list[Neighbor]  # neighbours that COULD produce the observed depth
    n_in_aperture: int
    n_unknown_mag: int
    depth_frac: float
    aperture_arcsec: float

    @property
    def verdict(self) -> str:
        return "capable_neighbor" if self.capable else "none_capable"


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


class StellarService:
    def __init__(self, gaia: GaiaLike, search_radius_arcsec: float = 2 * TESS_PIXEL_ARCSEC) -> None:
        self.gaia, self.search_radius = gaia, search_radius_arcsec

    def profile(self, obj: AstronomicalObject) -> StellarProfile | None:
        recs = self.gaia.lookup(obj)
        if not recs:
            return None
        rec = recs[0]
        v = rec.values
        prof = StellarProfile(
            str(v.get("source_id")), _f(v.get("phot_g_mean_mag")), _f(v.get("teff_gspphot")),
            _f(v.get("logg_gspphot")), _f(v.get("radius_gspphot")), _f(v.get("ruwe")),
            star_record=rec)
        rows, _ = self.gaia.cone_for_object_epoch(
            obj.ra_deg, obj.dec_deg, obj.pm_ra_mas_yr, obj.pm_dec_mas_yr, obj.epoch,
            self.search_radius)
        for r in rows:
            if str(r.get("source_id")) == prof.source_id:
                continue
            g = _f(r.get("phot_g_mean_mag"))
            prof.neighbors.append(Neighbor(
                str(r["source_id"]), float(r["_sep_arcsec"]), g,
                None if g is None or prof.g_mag is None else g - prof.g_mag))
        prof.cone_record = CatalogRecord(
            "Gaia", "gaiadr3.gaia_source (cone)", prof.source_id or "", {"n_rows": len(rows)},
            None, self.gaia.last_query, getattr(self.gaia, "url", "gaia-tap"))
        return prof


def assess_contamination(profile: StellarProfile, depth_frac: float,
                         aperture_arcsec: float = TESS_PIXEL_ARCSEC) -> ContaminationAssessment:
    inside = [n for n in profile.neighbors if n.sep_arcsec <= aperture_arcsec]
    unknown = [n for n in inside if n.delta_g is None]
    known = [n for n in inside if n.delta_g is not None]
    ratio = {n.source_id: 10 ** (-0.4 * float(n.delta_g or 0.0)) for n in known}
    total = 1.0 + sum(ratio.values())
    capable = [n for n in known if ratio[n.source_id] / total >= depth_frac]
    return ContaminationAssessment(capable, len(inside), len(unknown), depth_frac, aperture_arcsec)
