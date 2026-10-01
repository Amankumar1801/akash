from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from akash_core.errors import ProviderError

from ..identifiers import adql_literal
from ..positions import angular_sep_arcsec
from .tap import TapClient

SIMBAD_TAP = "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"
_COLS = "b.oid, b.main_id, b.ra, b.dec, b.pmra, b.pmdec, b.plx_value"


@dataclass(frozen=True)
class SimbadObject:
    oid: int
    main_id: str
    ra: float
    dec: float
    pmra: float | None
    pmdec: float | None
    parallax: float | None
    separation_arcsec: float = 0.0


def _row_to_obj(r: dict[str, Any], sep: float = 0.0) -> SimbadObject:
    if r.get("ra") is None or r.get("dec") is None:
        raise ProviderError(f"SIMBAD record {r.get('main_id')!r} has no coordinates")
    return SimbadObject(
        oid=int(r["oid"]), main_id=str(r["main_id"]), ra=float(r["ra"]), dec=float(r["dec"]),
        pmra=None if r.get("pmra") is None else float(r["pmra"]),
        pmdec=None if r.get("pmdec") is None else float(r["pmdec"]),
        parallax=None if r.get("plx_value") is None else float(r["plx_value"]),
        separation_arcsec=sep,
    )


class SimbadClient:
    name = "simbad"

    def __init__(self, tap: TapClient) -> None:
        self.tap = tap

    def by_identifier(self, ident: str) -> list[SimbadObject]:
        lit = adql_literal(ident)
        rows = self.tap.query(
            f"SELECT DISTINCT {_COLS} FROM basic AS b JOIN ident AS i ON i.oidref = b.oid "
            f"WHERE i.id = '{lit}'"
        )
        return [_row_to_obj(r) for r in rows]

    def cone(self, ra: float, dec: float, radius_arcsec: float) -> list[SimbadObject]:
        rows = self.tap.query(
            f"SELECT {_COLS} FROM basic AS b WHERE CONTAINS(POINT('ICRS', b.ra, b.dec), "
            f"CIRCLE('ICRS', {ra:.8f}, {dec:.8f}, {radius_arcsec / 3600.0:.8f})) = 1"
        )
        out = [
            _row_to_obj(r, angular_sep_arcsec(ra, dec, float(r["ra"]), float(r["dec"])))
            for r in rows
            if r.get("ra") is not None and r.get("dec") is not None
        ]
        return sorted(out, key=lambda o: o.separation_arcsec)

    def identifiers(self, oid: int) -> list[str]:
        rows = self.tap.query(f"SELECT id FROM ident WHERE oidref = {int(oid)}")
        return [str(r["id"]) for r in rows]
