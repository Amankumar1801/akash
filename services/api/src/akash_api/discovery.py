"""Discovery feed: a review queue over finished investigations, built from stored assessments.

Ranking is transparent and is NOT a score: candidates are ordered by a fixed, documented category
order, then by a stated secondary key. Nothing is combined into a number, and the response says in
words what the order means (and what it does not). Scale: this scans the most recent
SCAN_LIMIT finished investigations per request; a materialised table is the upgrade path."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from akash_core.enums import TriageCategory

from .db import StoreContext
from .jobs import SUCCEEDED, JobStore
from .research import LabelStore

SCAN_LIMIT = 500
KNOWN = {TriageCategory.KNOWN_CONFIRMED.value, TriageCategory.KNOWN_CANDIDATE.value,
         TriageCategory.KNOWN_FALSE_POSITIVE.value}
# What most deserves a human look first. Not a probability of anything.
TRIAGE_ORDER: tuple[str, ...] = (
    "new_signal_review", "models_disagree", "insufficient_data", "known_candidate",
    "likely_systematic", "known_false_positive", "known_confirmed")
Sort = Literal["triage", "anomaly", "snr", "recent"]
RANKING_TEXT = {
    "triage": "Ordered by triage category (unlisted signals and model disagreements first), "
              "then by anomaly percentile, then by recency.",
    "anomaly": "Ordered by anomaly percentile within its reference population, then recency.",
    "snr": "Ordered by the transit signal-to-noise, then recency.",
    "recent": "Ordered by when the investigation finished.",
}
NOT_A_SCORE = ("This is a review queue. The order says what to look at first, not how likely "
               "anything is to be real.")


def signal_strength(snr: float | None) -> str:
    if snr is None:
        return "none"
    return "strong" if snr >= 15 else "moderate" if snr >= 7 else "weak"


@dataclass
class Filters:
    categories: set[str]
    exclude_known: bool
    min_anomaly: float | None
    min_snr: float | None
    reviewed: Literal["any", "reviewed", "unreviewed"]
    q: str | None
    sort: Sort


def build_cards(
    ctx: StoreContext, owner: str | None, me: str
) -> tuple[list[dict[str, Any]], int, bool]:
    """Latest assessed investigation per object, visible to `owner` (None = everyone)."""
    jobs = JobStore(ctx.conn).list_for_owner(owner, SCAN_LIMIT + 1, 0)
    truncated = len(jobs) > SCAN_LIMIT
    labels = LabelStore(ctx.conn).latest_by_investigation()
    seen_objects: set[str] = set()
    cards: list[dict[str, Any]] = []
    scanned = 0
    for j in jobs[:SCAN_LIMIT]:
        if j.status != SUCCEEDED or j.category is None:
            continue
        scanned += 1
        oid = j.params.get("object_id")
        if oid in seen_objects:  # newest first, so the first one seen is the latest
            continue
        a = ctx.evidence.get_assessment(UUID(j.job_id))
        if a is None:
            continue
        seen_objects.add(str(oid))
        obj = ctx.repo.get_object(a.object_id)
        d = a.model_dump(mode="json")
        snr = d["transit"]["snr"] if d["transit"] else None
        revs = labels.get(j.job_id, [])
        vet = {"pass": 0, "warn": 0, "fail": 0, "unknown": 0}
        for v in d["vetting"].values():
            vet[v] = vet.get(v, 0) + 1
        cards.append({
            "investigation_id": j.job_id, "object_id": str(a.object_id),
            "name": obj.canonical_name if obj else "unknown object",
            "ra_deg": obj.ra_deg if obj else None, "dec_deg": obj.dec_deg if obj else None,
            "triage_category": d["triage_category"],
            "anomaly": ({"percentile": d["anomaly"]["percentile"],
                         "reference_population": d["anomaly"]["reference_population"],
                         "category": d["anomaly"]["category"]} if d["anomaly"] else None),
            "prediction": ({"probability": d["prediction"]["planet_like_probability"],
                            "interval_90": d["prediction"]["interval_90"],
                            "calibrated": d["prediction"]["calibrated"],
                            "models_disagree": bool(d["prediction"]["disagreement"]
                                                    and d["prediction"]["disagreement"]["flag"])}
                           if d["prediction"] else None),
            "transit": ({"snr": snr, "period_d": d["transit"]["period_d"]["value"],
                         "depth_ppm": d["transit"]["depth_ppm"]} if d["transit"] else None),
            "signal_strength": signal_strength(snr),
            "known_status": d["known_status"]["status"] if d["known_status"] else None,
            "known_source": d["known_status"]["source"] if d["known_status"] else None,
            "data_quality": d["data_quality"]["grade"],
            "vetting": vet, "n_conflicts": len(d["conflicting_evidence"]),
            "recommended_followup": d["recommended_followup"][:4],
            "finished_at": j.finished_at,
            "review": {"n_reviewers": len(revs), "mine": next(
                (lab for who, lab in revs if who == me), None),
                "labels": sorted({lab for _, lab in revs})},
        })
    return cards, scanned, truncated


def apply(cards: list[dict[str, Any]], f: Filters) -> list[dict[str, Any]]:
    out = []
    for c in cards:
        if f.categories and c["triage_category"] not in f.categories:
            continue
        if f.exclude_known and (c["triage_category"] in KNOWN
                                or c["known_status"] in ("confirmed", "candidate",
                                                         "false_positive")):
            continue
        pct = c["anomaly"]["percentile"] if c["anomaly"] else None
        if f.min_anomaly is not None and (pct is None or pct < f.min_anomaly):
            continue
        snr = c["transit"]["snr"] if c["transit"] else None
        if f.min_snr is not None and (snr is None or snr < f.min_snr):
            continue
        mine = c["review"]["mine"]
        if f.reviewed == "reviewed" and mine is None:
            continue
        if f.reviewed == "unreviewed" and mine is not None:
            continue
        if f.q and f.q.lower() not in c["name"].lower():
            continue
        out.append(c)
    return sort_cards(out, f.sort)


def sort_cards(cards: list[dict[str, Any]], key: Sort) -> list[dict[str, Any]]:
    def pct(c: dict[str, Any]) -> float:
        return c["anomaly"]["percentile"] if c["anomaly"] else -1.0

    def snr(c: dict[str, Any]) -> float:
        return c["transit"]["snr"] if c["transit"] else -1.0

    def rec(c: dict[str, Any]) -> float:
        return c["finished_at"] or 0.0
    if key == "anomaly":
        return sorted(cards, key=lambda c: (-pct(c), -rec(c)))
    if key == "snr":
        return sorted(cards, key=lambda c: (-snr(c), -rec(c)))
    if key == "recent":
        return sorted(cards, key=lambda c: -rec(c))
    rank = {k: i for i, k in enumerate(TRIAGE_ORDER)}
    return sorted(cards, key=lambda c: (rank.get(c["triage_category"], 99), -pct(c), -rec(c)))
