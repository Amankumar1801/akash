"""MAST light-curve provider for TESS (SPOC) and Kepler, via the MAST CAOM JSON API.

NOTE: field names follow the documented CAOM schema; verify against live responses with
scripts/record_fixtures.py before trusting them (see docs/adr/0002).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from akash_core.enums import Modality
from akash_core.errors import ProviderError
from akash_core.schemas import AstronomicalObject

from ..base import FetchedArtifact, ObservationRef, ObsFilter, ProviderHealth
from ..http import ResilientClient
from ..lightcurve import KEPLER, TESS, MissionSpec, NormalizedLightCurve, parse_lightcurve_fits

MAST_API = "https://mast.stsci.edu/api/v0/invoke"
MAST_DOWNLOAD = "https://mast.stsci.edu/api/v0.1/Download/file"
CONE_RADIUS_DEG = 0.003  # ~10 arcsec


@dataclass(frozen=True)
class MissionConfig:
    spec: MissionSpec
    collection: str  # CAOM obs_collection
    provenance: str  # CAOM provenance_name
    dataset: str
    subgroups: tuple[str, ...]  # productSubGroupDescription values that are light curves
    alias_ns: str

    def target_name(self, ident: str) -> str:
        return ident if self.spec.name == "TESS" else f"kplr{int(ident):09d}"


TESS_SPOC = MissionConfig(TESS, "TESS", "SPOC", "TESS-SPOC", ("LC",), "TIC")
KEPLER_LC = MissionConfig(KEPLER, "Kepler", "Kepler", "Kepler-LC", ("LLC", "SLC"), "KIC")


class MastLightCurveProvider:
    def __init__(self, http: ResilientClient, cfg: MissionConfig) -> None:
        self.http, self.cfg = http, cfg
        self.name = f"mast:{cfg.collection.lower()}"

    def health(self) -> ProviderHealth:
        return ProviderHealth(self.name, self.http.breaker.state, self.http.last_error)

    def _invoke(self, service: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        req = {"service": service, "params": params, "format": "json", "pagesize": 2000}
        resp = self.http.post(MAST_API, data={"request": json.dumps(req)})
        try:
            body = resp.json()
        except ValueError as e:
            raise ProviderError(f"{self.name}: non-JSON MAST response") from e
        if body.get("status") not in (None, "COMPLETE"):
            raise ProviderError(f"{self.name}: MAST status {body.get('status')}: {body.get('msg')}")
        return list(body.get("data", []))

    def list_observations(self, obj: AstronomicalObject, flt: ObsFilter) -> list[ObservationRef]:
        rows = self._invoke(
            "Mast.Caom.Cone", {"ra": obj.ra_deg, "dec": obj.dec_deg, "radius": CONE_RADIUS_DEG}
        )
        rows = [
            r for r in rows
            if r.get("obs_collection") == self.cfg.collection
            and r.get("dataproduct_type") == "timeseries"
            and r.get("provenance_name") == self.cfg.provenance
        ]
        ident = obj.alias(self.cfg.alias_ns)
        match = "positional"
        if ident is not None:
            want = self.cfg.target_name(ident)
            by_alias = [r for r in rows if str(r.get("target_name")) == want]
            rows, match = by_alias, "alias"
        if flt.segments is not None:
            rows = [r for r in rows if r.get("sequence_number") in flt.segments]
        rows.sort(key=lambda r: (r.get("sequence_number") or 0, str(r.get("obs_id"))))

        refs: list[ObservationRef] = []
        for r in rows:
            prods = self._invoke("Mast.Caom.Products", {"obsid": str(r["obsid"])})
            for p in prods:
                if p.get("productSubGroupDescription") not in self.cfg.subgroups:
                    continue
                fname = str(p["productFilename"])
                refs.append(ObservationRef(
                    provider=self.name, dataset=self.cfg.dataset,
                    native_obs_id=fname, modality=Modality.LIGHT_CURVE,
                    url=f"{MAST_DOWNLOAD}?uri={p['dataURI']}",
                    meta={
                        "obsid": str(r["obsid"]), "segment": r.get("sequence_number"),
                        "t_min": r.get("t_min"), "t_max": r.get("t_max"),
                        "size": p.get("size"), "target_name": r.get("target_name"),
                        "identity_match": match,
                    },
                ))
        if flt.max_observations is not None:
            refs = refs[: flt.max_observations]
        return refs

    def fetch(self, ref: ObservationRef) -> FetchedArtifact:
        resp = self.http.get(ref.url)
        content = resp.content
        expected = ref.meta.get("size")
        if isinstance(expected, int) and expected > 0 and len(content) != expected:
            raise ProviderError(
                f"{self.name}: truncated download for {ref.native_obs_id}: "
                f"{len(content)} != {expected} bytes"
            )
        return FetchedArtifact(ref=ref, content=content, source_uri=ref.url)

    def normalize(self, art: FetchedArtifact) -> NormalizedLightCurve:
        return parse_lightcurve_fits(art.content, self.cfg.spec)
