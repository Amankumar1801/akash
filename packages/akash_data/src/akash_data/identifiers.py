"""Parse user queries into structured identifiers. Pure, no I/O.

Everything that later reaches an ADQL query must pass the strict allowlist here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from akash_core.errors import ValidationFailure

Kind = Literal["alias", "coords", "name"]

_SAFE_NAME = re.compile(r"^[A-Za-z0-9 .+\-_*\[\]()/:]{1,80}$")

_NUM_ALIASES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^TIC[\s_-]*(\d{1,10})$", re.I), "TIC"),
    (re.compile(r"^KIC[\s_-]*(\d{1,9})$", re.I), "KIC"),
    (re.compile(r"^(?:GAIA[\s_-]*(?:E?DR3)?)[\s_-]*(\d{5,19})$", re.I), "GAIA_DR3"),
    (re.compile(r"^GAIA[\s_-]*DR2[\s_-]*(\d{5,19})$", re.I), "GAIA_DR2"),
]
_PLANET_ALIASES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^KOI[\s_-]*(\d+(?:\.\d+)?)$", re.I), "KOI"),
    (re.compile(r"^TOI[\s_-]*(\d+(?:\.\d+)?)$", re.I), "TOI"),
]
_SDSS = re.compile(r"^SDSS[\s_-]*J(\d{6}\.\d+[+-]\d{6}\.\d+)$", re.I)

_DECIMAL_PAIR = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*[,\s]\s*([+-]?\d+(?:\.\d+)?)\s*$")
_SEXA = re.compile(
    r"^\s*(\d{1,2})[h:\s]\s*(\d{1,2})[m:\s]\s*(\d{1,2}(?:\.\d+)?)s?\s*[,\s]?\s*"
    r"([+-]?\d{1,2})[d°:\s]\s*(\d{1,2})[m'’:\s]\s*(\d{1,2}(?:\.\d+)?)[s\"”]?\s*$",
    re.I,
)


@dataclass(frozen=True)
class ParsedIdentifier:
    kind: Kind
    raw: str
    namespace: str | None = None
    identifier: str | None = None
    ra_deg: float | None = None
    dec_deg: float | None = None

    @property
    def simbad_form(self) -> str:
        """Identifier string as SIMBAD's ident table normalises it."""
        assert self.namespace and self.identifier
        if self.namespace == "GAIA_DR3":
            return f"Gaia DR3 {self.identifier}"
        if self.namespace == "GAIA_DR2":
            return f"Gaia DR2 {self.identifier}"
        if self.namespace == "SDSS":
            return f"SDSS J{self.identifier}"
        return f"{self.namespace} {self.identifier}"


def _check_coords(ra: float, dec: float, raw: str) -> tuple[float, float]:
    if not (0.0 <= ra < 360.0) or not (-90.0 <= dec <= 90.0):
        raise ValidationFailure(f"coordinates out of range: {raw!r}")
    return ra, dec


def _sexagesimal(h: str, m: str, s: str, d: str, dm: str, ds: str, raw: str) -> tuple[float, float]:
    ra = (float(h) + float(m) / 60 + float(s) / 3600) * 15.0
    sign = -1.0 if d.strip().startswith("-") else 1.0
    dec = sign * (abs(float(d)) + float(dm) / 60 + float(ds) / 3600)
    if float(h) >= 24 or float(m) >= 60 or float(s) >= 60 or float(dm) >= 60 or float(ds) >= 60:
        raise ValidationFailure(f"invalid sexagesimal coordinates: {raw!r}")
    return _check_coords(ra, dec, raw)


def parse_identifier(query: str) -> ParsedIdentifier:
    q = " ".join(query.strip().split())
    if not q:
        raise ValidationFailure("empty query")

    for pat, ns in _NUM_ALIASES:
        if m := pat.match(q):
            return ParsedIdentifier("alias", q, namespace=ns, identifier=str(int(m.group(1))))
    for pat, ns in _PLANET_ALIASES:
        if m := pat.match(q):
            return ParsedIdentifier("alias", q, namespace=ns, identifier=m.group(1))
    if m := _SDSS.match(q):
        return ParsedIdentifier("alias", q, namespace="SDSS", identifier=m.group(1))

    if m := _DECIMAL_PAIR.match(q):
        ra, dec = _check_coords(float(m.group(1)), float(m.group(2)), q)
        return ParsedIdentifier("coords", q, ra_deg=ra, dec_deg=dec)
    if m := _SEXA.match(q):
        h, mi, s, dd, dm, ds = m.groups()
        ra, dec = _sexagesimal(h, mi, s, dd, dm, ds, raw=q)
        return ParsedIdentifier("coords", q, ra_deg=ra, dec_deg=dec)

    if not _SAFE_NAME.match(q):
        raise ValidationFailure(f"query contains disallowed characters: {query!r}")
    return ParsedIdentifier("name", q, namespace=None, identifier=q)


def adql_literal(value: str) -> str:
    """Escape a string for an ADQL literal. Callers should still allowlist first."""
    if not _SAFE_NAME.match(value):
        raise ValidationFailure(f"unsafe ADQL literal: {value!r}")
    return value.replace("'", "''")
