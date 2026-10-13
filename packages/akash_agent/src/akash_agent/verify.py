"""Checks an answer against what was actually retrieved. Nothing unverified reaches the user.

The model may phrase things; it may not invent evidence, launder a model output into a fact,
quote numbers the cited rows do not contain, or make claims AKASH does not make."""

from __future__ import annotations

import json
import re
from typing import Any

from .types import AgentAnswer, Violation

FACT_CHANNELS = {"observed_fact", "data_quality", "catalog_status", "cross_survey"}
MODEL_CHANNELS = {"model_prediction", "anomaly"}
NEEDS_CITATION = {"fact", "prediction", "interpretation", "uncertainty"}

_NEG = re.compile(r"\b(not|never|no|n't|cannot|can't)\b", re.I)
_FORBIDDEN: list[tuple[str, re.Pattern[str], bool]] = [  # (code, pattern, tolerated_if_negated)
    ("claims_discovery", re.compile(r"\bdiscover(?:ed|y|ies|ing)?\b", re.I), True),
    ("claims_new_planet", re.compile(r"\bnew (?:exo)?planet\b", re.I), True),
    ("claims_detection", re.compile(
        r"\b(?:detected|found|identified) an? (?:new )?(?:exo)?planet\b|\bplanet detected\b", re.I),
     True),
    ("claims_identity", re.compile(r"\bis an? (?:exo)?planet\b(?!\s*(?:candidate|-?like))", re.I),
     True),
    ("overclaims_certainty", re.compile(
        r"\b(?:proves?|proven|definitely|certainly|undoubtedly|without (?:a )?doubt"
        r"|guarantee[sd]?)\b",
        re.I), False),
    ("claims_life", re.compile(r"\b(?:aliens?|extraterrestrial|technosignatures?)\b", re.I), False),
]
_NUM = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?%?")
_ID_PREFIX = re.compile(r"(?:TIC|KIC|TOI|KOI|DR|Sector|Gaia)[\s-]*$", re.I)


def numbers_in(text: str) -> list[float | None]:
    """Numbers a statement asserts. Catalog identifiers and huge integers are not claims."""
    out: list[float | None] = []
    for m in _NUM.finditer(text):
        tok = m.group().rstrip("%").replace(",", "")
        if _ID_PREFIX.search(text[: m.start()]):
            continue
        try:
            v = float(tok)
        except ValueError:
            continue
        if "." not in tok and abs(v) >= 1_000_000:
            continue
        out.append(v)
    return out


def _decimals(tok: str) -> int:
    return len(tok.split(".")[1]) if "." in tok else 0


def _row_numbers(row: dict[str, Any]) -> set[float]:
    blob = " ".join([row.get("observation", ""),
                     json.dumps(row.get("result", {}), default=str),
                     json.dumps(row.get("uncertainty") or {}, default=str),
                     json.dumps(row.get("source", {}), default=str)])
    vals: set[float] = set()
    for m in _NUM.finditer(blob):
        try:
            v = float(m.group().rstrip("%").replace(",", ""))
        except ValueError:
            continue
        vals.add(v)
        if 0 < abs(v) <= 1:
            vals.add(v * 100)  # 0.91 may be quoted as 91%
        if abs(v) > 1:
            vals.add(v / 100)
    return vals


def _supported(n: float, token_text: str, allowed: set[float]) -> bool:
    half = 0.5 * 10 ** (-_decimals(token_text)) + 1e-9
    return any(abs(n - a) <= max(half, 0.005 * abs(a)) for a in allowed)


def verify(answer: AgentAnswer, rows: dict[str, dict[str, Any]], seen: set[str]) -> list[Violation]:
    v: list[Violation] = []
    kinds = [s.kind for s in answer.statements]
    if "prediction" in kinds and "uncertainty" not in kinds:
        v.append(Violation("prediction_without_uncertainty",
                           "an answer that reports a model output must also state its uncertainty"))
    for i, s in enumerate(answer.statements):
        cited: list[dict[str, Any]] = []
        for eid in s.evidence_ids:
            key = eid.lower()
            row = rows.get(key)
            if row is None:
                v.append(Violation("unknown_evidence", f"{eid} is not evidence in this "
                                   "investigation", i))
            elif key not in seen:
                v.append(Violation("not_retrieved", f"{eid} was never retrieved with a tool", i))
            else:
                cited.append(row)
        if s.kind in NEEDS_CITATION and not s.evidence_ids:
            v.append(Violation("missing_citation", f"a {s.kind} must cite evidence ids", i))
        chans = {r["channel"] for r in cited}
        if s.kind == "fact" and cited and not (chans & FACT_CHANNELS):
            v.append(Violation("model_output_as_fact", "a fact must cite a measurement, "
                               "catalog or quality row, not only a model output", i))
        if s.kind == "prediction" and cited and not (chans & MODEL_CHANNELS):
            v.append(Violation("prediction_without_model", "a prediction must cite a model "
                               "or anomaly row", i))
        for code, pat, tolerate_neg in _FORBIDDEN:
            if pat.search(s.text) and not (tolerate_neg and _NEG.search(s.text)):
                v.append(Violation(code, f"wording not allowed: {pat.search(s.text).group()!r}",  # type: ignore[union-attr]
                                   i))
        if re.search(r"\bconfirmed\b", s.text, re.I) and not any(
                r["channel"] == "catalog_status" and r["result"].get("status") == "confirmed"
                for r in cited):
            v.append(Violation("confirmed_without_catalog", "'confirmed' may only be used when "
                               "citing a catalog row whose status is confirmed", i))
        allowed: set[float] = set().union(*(_row_numbers(r) for r in cited)) if cited else set()
        for m in _NUM.finditer(s.text):
            toks = numbers_in(m.group())
            if not toks or toks[0] is None:
                continue
            if _ID_PREFIX.search(s.text[: m.start()]):
                continue
            if not _supported(toks[0], m.group().rstrip("%").replace(",", ""), allowed):
                v.append(Violation("unsupported_number", f"{m.group()} does not appear in the "
                                   "cited evidence", i))
    return v
