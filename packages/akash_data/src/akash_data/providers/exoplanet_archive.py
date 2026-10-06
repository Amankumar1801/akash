from __future__ import annotations

from datetime import UTC, datetime

from akash_core.schemas import AstronomicalObject

from ..base import CatalogRecord, ProviderHealth
from ..http import ResilientClient
from .tap import TapClient

IPAC_TAP = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"

TOI_STATUS = {
    "CP": "confirmed", "KP": "confirmed", "PC": "candidate", "APC": "candidate",
    "FP": "false_positive", "FA": "false_positive",
}
KOI_STATUS = {
    "CONFIRMED": "confirmed", "CANDIDATE": "candidate", "FALSE POSITIVE": "false_positive",
}


def aggregate_status(statuses: list[str | None]) -> str:
    """Overall status across several catalog rows. Precedence is documented, not clever:
    any confirmed -> confirmed; else any candidate -> candidate; else all false_positive
    -> false_positive; else none."""
    s = {x for x in statuses if x}
    if "confirmed" in s:
        return "confirmed"
    if "candidate" in s:
        return "candidate"
    if s == {"false_positive"}:
        return "false_positive"
    return "none"


class ExoplanetArchiveProvider:
    name = "exoplanet_archive"

    def __init__(self, http: ResilientClient, url: str = IPAC_TAP) -> None:
        self.http = http
        self.url = url
        self.tap = TapClient(http, url)
        # queries of the latest lookup: an EMPTY result still needs provenance of what was asked
        self.last_queries: list[str] = []

    def health(self) -> ProviderHealth:
        return ProviderHealth(self.name, self.http.breaker.state, self.http.last_error)

    def lookup(self, obj: AstronomicalObject) -> list[CatalogRecord]:
        now = datetime.now(UTC)
        out: list[CatalogRecord] = []
        self.last_queries = []
        if tic := obj.alias("TIC"):
            q = (
                "select tid, toi, tfopwg_disp, pl_orbper, pl_trandep, pl_trandurh "
                f"from toi where tid = {int(tic)}"
            )
            self.last_queries.append(q)
            for r in self.tap.query(q):
                disp = str(r.get("tfopwg_disp") or "").strip().upper()
                out.append(CatalogRecord(
                    "NASA Exoplanet Archive", "toi", str(r.get("toi")), r,
                    TOI_STATUS.get(disp), q, self.url, now))
        if kic := obj.alias("KIC"):
            q = (
                "select kepid, kepoi_name, koi_disposition, koi_pdisposition, koi_period "
                f"from cumulative where kepid = {int(kic)}"
            )
            self.last_queries.append(q)
            for r in self.tap.query(q):
                disp = str(r.get("koi_disposition") or "").strip().upper()
                out.append(CatalogRecord(
                    "NASA Exoplanet Archive", "cumulative", str(r.get("kepoi_name")), r,
                    KOI_STATUS.get(disp), q, self.url, now))
        return out
