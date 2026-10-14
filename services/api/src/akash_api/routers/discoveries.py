from __future__ import annotations

from typing import Annotated, Any, Literal

from akash_core.enums import TriageCategory
from fastapi import APIRouter, Depends, Query

from ..auth import Principal, Role
from ..db import StoreContext
from ..deps import get_ctx, rate_limited, require
from ..discovery import NOT_A_SCORE, RANKING_TEXT, Filters, apply, build_cards

router = APIRouter(prefix="/v1")
READ = [Depends(rate_limited("general", "api_rate_per_min"))]
MAX_SKY = 5000


def _owner(p: Principal) -> str | None:
    return None if p.at_least(Role.ADMIN) else p.name


@router.get("/discoveries", dependencies=READ)
def discoveries(
        category: Annotated[list[TriageCategory] | None, Query()] = None,
        exclude_known: bool = False,
        min_anomaly_percentile: Annotated[float | None, Query(ge=0, le=100)] = None,
        min_snr: Annotated[float | None, Query(ge=0, le=1000)] = None,
        reviewed: Literal["any", "reviewed", "unreviewed"] = "any",
        q: Annotated[str | None, Query(max_length=60)] = None,
        sort: Literal["triage", "anomaly", "snr", "recent"] = "triage",
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        offset: Annotated[int, Query(ge=0)] = 0,
        principal: Principal = Depends(require(Role.VIEWER)),
        ctx: StoreContext = Depends(get_ctx)) -> dict[str, Any]:
    cards, scanned, truncated = build_cards(ctx, _owner(principal), principal.name)
    rows = apply(cards, Filters({c.value for c in category or []}, exclude_known,
                                min_anomaly_percentile, min_snr, reviewed, q, sort))
    return {"items": rows[offset:offset + limit], "total": len(rows), "scanned": scanned,
            "truncated": truncated, "ranking": {"sort": sort, "rule": RANKING_TEXT[sort],
                                                "caveat": NOT_A_SCORE},
            "disclaimer": "AKASH assists investigation; it does not independently establish "
                          "discoveries."}


@router.get("/sky", dependencies=READ)
def sky(principal: Principal = Depends(require(Role.VIEWER)),
        ctx: StoreContext = Depends(get_ctx)) -> dict[str, Any]:
    """Compact points for the sky map: investigated objects only, capped."""
    cards, _, truncated = build_cards(ctx, _owner(principal), principal.name)
    pts = [{"investigation_id": c["investigation_id"], "name": c["name"], "ra_deg": c["ra_deg"],
            "dec_deg": c["dec_deg"], "category": c["triage_category"],
            "anomaly_percentile": c["anomaly"]["percentile"] if c["anomaly"] else None}
           for c in cards if c["ra_deg"] is not None and c["dec_deg"] is not None]
    return {"points": pts[:MAX_SKY], "n": len(pts), "capped": len(pts) > MAX_SKY,
            "truncated": truncated,
            "note": "Only objects that have been investigated appear here. This is not a survey "
                    "map."}
