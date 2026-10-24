from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from akash_core.errors import ProviderError
from akash_core.schemas import AstronomicalObject

from ..base import CatalogRecord, ProviderHealth
from ..http import ResilientClient
from ..positions import angular_sep_arcsec, propagate
from .tap import TapClient

GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
GAIA_DR3_EPOCH = 2016.0
_CORE = ("source_id", "ra", "dec")
_OPTIONAL = ("pmra", "pmdec", "parallax", "phot_g_mean_mag", "ruwe",
             "teff_gspphot", "logg_gspphot")
# Stellar radius is NOT a column of gaia_source; Gaia keeps it in a separate table.
_ASTRO_TABLE = "gaiadr3.astrophysical_parameters"
_ASTRO_COLS = "radius_gspphot, radius_flame"


class GaiaProvider:
    name = "gaia"
    release = "DR3"

    def __init__(self, http: ResilientClient, url: str = GAIA_TAP) -> None:
        self.http = http
        self.url = url
        self.tap = TapClient(http, url, upper_params=True)
        self.last_query = ""  # exact ADQL of the most recent query, for provenance
        self._cols: tuple[str, ...] = (*_CORE, *_OPTIONAL)
        self.dropped: list[str] = []  # optional columns this archive refused (schema drift)

    def _query(self, template: str) -> list[dict[str, Any]]:
        """Run `template` (with a {cols} slot). If the archive rejects the request (HTTP 400), find
        which optional columns it does not know, drop them for good and retry once, so one renamed
        column costs that column instead of every stellar parameter."""
        try:
            self.last_query = template.format(cols=", ".join(self._cols))
            return self.tap.query(self.last_query)
        except ProviderError as first:
            if "HTTP 400" not in str(first):
                raise
            ok = []
            for c in _OPTIONAL:
                try:
                    self.tap.query(f"SELECT TOP 1 {c} FROM gaiadr3.gaia_source")
                    ok.append(c)
                except ProviderError:
                    self.dropped.append(c)
            if not self.dropped:
                raise
            self._cols = (*_CORE, *ok)
            self.last_query = template.format(cols=", ".join(self._cols))
            return self.tap.query(self.last_query)

    def _add_radius(self, row: dict[str, Any], source_id: int) -> str:
        """Add radius_gspphot / radius_flame from the astrophysical-parameters table. A failure
        here costs the radius only (recorded in `dropped`), never the rest of the record."""
        q = f"SELECT {_ASTRO_COLS} FROM {_ASTRO_TABLE} WHERE source_id = {source_id}"
        try:
            extra = self.tap.query(q)
        except ProviderError:
            if _ASTRO_TABLE not in self.dropped:
                self.dropped.append(_ASTRO_TABLE)
            return q
        if extra:
            row.update(extra[0])
        return q

    def health(self) -> ProviderHealth:
        return ProviderHealth(self.name, self.http.breaker.state, self.http.last_error)

    def cone(self, ra: float, dec: float, radius_arcsec: float) -> list[dict[str, Any]]:
        """Raw rows sorted by separation; each gets a `_sep_arcsec` field."""
        adql = (
            "SELECT TOP 20 {cols} FROM gaiadr3.gaia_source WHERE 1 = CONTAINS("
            f"POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra:.8f}, {dec:.8f}, "
            f"{radius_arcsec / 3600.0:.8f}))"
        )
        rows = self._query(adql)
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
        rows = self._query(
            "SELECT {cols} FROM gaiadr3.gaia_source WHERE source_id = " + str(int(sid)))
        adql = self.last_query
        for r in rows:
            adql += "; " + self._add_radius(r, int(sid))
        now = datetime.now(UTC)
        return [
            CatalogRecord(
                source="Gaia", table="gaiadr3.gaia_source", native_id=str(r["source_id"]),
                values=r, status=None, query=adql, source_uri=self.url, retrieved_at=now,
            )
            for r in rows
        ]
