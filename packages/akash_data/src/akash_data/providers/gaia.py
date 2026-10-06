from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from akash_core.schemas import AstronomicalObject

from ..base import CatalogRecord, ProviderHealth
from ..http import ResilientClient
from ..positions import angular_sep_arcsec, propagate
from .tap import TapClient

GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
GAIA_DR3_EPOCH = 2016.0
_COLS = (
    "source_id, ra, dec, pmra, pmdec, parallax, phot_g_mean_mag, ruwe, "
    "teff_gspphot, logg_gspphot, radius_gspphot"
)


class GaiaProvider:
    name = "gaia"
    release = "DR3"

    def __init__(self, http: ResilientClient, url: str = GAIA_TAP) -> None:
        self.http = http
        self.url = url
        self.tap = TapClient(http, url, upper_params=True)
        self.last_query = ""  # exact ADQL of the most recent query, for provenance

    def health(self) -> ProviderHealth:
        return ProviderHealth(self.name, self.http.breaker.state, self.http.last_error)

    def cone(self, ra: float, dec: float, radius_arcsec: float) -> list[dict[str, Any]]:
        """Raw rows sorted by separation; each gets a `_sep_arcsec` field."""
        adql = (
            f"SELECT TOP 20 {_COLS} FROM gaiadr3.gaia_source WHERE 1 = CONTAINS("
            f"POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra:.8f}, {dec:.8f}, "
            f"{radius_arcsec / 3600.0:.8f}))"
        )
        self.last_query = adql
        rows = self.tap.query(adql)
        for r in rows:
            r["_sep_arcsec"] = angular_sep_arcsec(ra, dec, float(r["ra"]), float(r["dec"]))
        return sorted(rows, key=lambda r: r["_sep_arcsec"])

    def cone_for_object_epoch(
        self, ra: float, dec: float, pmra: float | None, pmdec: float | None,
        epoch: float, radius_arcsec: float,
    ) -> tuple[list[dict[str, Any]], tuple[float, float]]:
        """Propagate the position to the Gaia epoch before matching."""
        ra2, dec2 = propagate(ra, dec, pmra, pmdec, epoch, GAIA_DR3_EPOCH)
        return self.cone(ra2, dec2, radius_arcsec), (ra2, dec2)

    def lookup(self, obj: AstronomicalObject) -> list[CatalogRecord]:
        sid = obj.alias("GAIA_DR3")
        if sid is None:
            return []
        adql = f"SELECT {_COLS} FROM gaiadr3.gaia_source WHERE source_id = {int(sid)}"
        rows = self.tap.query(adql)
        now = datetime.now(UTC)
        return [
            CatalogRecord(
                source="Gaia", table="gaiadr3.gaia_source", native_id=str(r["source_id"]),
                values=r, status=None, query=adql, source_uri=self.url, retrieved_at=now,
            )
            for r in rows
        ]
