"""Minimal TAP (ADQL) sync client shared by SIMBAD, Gaia and the NASA Exoplanet Archive."""

from __future__ import annotations

from typing import Any

from akash_core.errors import ProviderError

from ..http import ResilientClient


class TapClient:
    def __init__(self, http: ResilientClient, url: str, upper_params: bool = False) -> None:
        self.http, self.url, self._upper = http, url, upper_params

    def query(self, adql: str) -> list[dict[str, Any]]:
        params = {"request": "doQuery", "lang": "ADQL", "format": "json", "query": adql}
        if self._upper:
            params = {k.upper(): v for k, v in params.items()}
        resp = self.http.post(self.url, data=params)
        try:
            body = resp.json()
        except ValueError as e:
            raise ProviderError(f"{self.http.name}: non-JSON TAP response") from e
        return parse_tap_json(body, self.http.name)


def parse_tap_json(body: Any, who: str = "tap") -> list[dict[str, Any]]:
    """Accepts {metadata:[{name}], data:[[...]]} (SIMBAD/Gaia) or a list of dicts (IPAC)."""
    if isinstance(body, list):
        if body and not isinstance(body[0], dict):
            raise ProviderError(f"{who}: unexpected list payload")
        return body
    if isinstance(body, dict) and "data" in body and "metadata" in body:
        cols = [m["name"] for m in body["metadata"]]
        return [dict(zip(cols, row, strict=True)) for row in body["data"]]
    raise ProviderError(f"{who}: unrecognised TAP JSON shape")
