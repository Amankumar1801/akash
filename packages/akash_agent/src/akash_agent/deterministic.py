"""An answer built straight from the evidence with no model involved.

Used when no provider is configured, and as the fallback when a model answer cannot be
verified. Statement text is the evidence's own recorded observation, so it cannot drift from it."""

from __future__ import annotations

from typing import Any

from .types import AgentAnswer, Statement
from .verify import verify

_FACT = {"observed_fact", "data_quality", "catalog_status", "cross_survey"}
_ORDER = ("catalog_status", "observed_fact", "data_quality", "model_prediction", "anomaly",
          "cross_survey")


def _stmt(row: dict[str, Any], kind: str) -> Statement:
    arrow = {"supports": "supports", "contradicts": "argues against",
             "inconclusive": "is inconclusive on"}.get(row["agreement"], "is neutral on")
    text = row["observation"].rstrip(".")
    if kind == "fact" and row["agreement"] != "neutral":
        text += f" (this {arrow} a planetary origin)"
    return Statement(text=text[:560], kind=kind,
                     evidence_ids=[row["evidence_id"]])


def build(assessment: dict[str, Any] | None, evidence: list[dict[str, Any]],
          question: str = "") -> AgentAnswer:
    rows = {r["evidence_id"].lower(): r for r in evidence}
    out: list[Statement] = []
    if assessment is None or not evidence:
        out.append(Statement(
            text="There is no assessment for this investigation, so there is nothing to explain.",
            kind="recommendation"))
    else:
        triage = str(assessment.get("triage_category") or assessment.get("triage") or "unknown")
        out.append(Statement(
            text=f"Triage category: {triage.replace('_', ' ')}. This is a reason for a human "
                 "to look, not a conclusion.", kind="recommendation"))
        by: dict[str, list[dict[str, Any]]] = {}
        for r in evidence:
            by.setdefault(r["channel"], []).append(r)
        for ch in _ORDER:
            for r in by.get(ch, [])[:3]:
                kind = "fact" if ch in _FACT else "prediction"
                out.append(_stmt(r, kind))
        if any(s.kind == "prediction" for s in out):
            unc = [r for r in by.get("model_prediction", []) + by.get("anomaly", [])
                   if r.get("uncertainty")]
            for r in unc[:1]:
                out.append(Statement(
                    text="The model outputs above carry stated uncertainty and are not "
                         "measurements; "
                         "see the cited row for its calibration and conformal set.",
                    kind="uncertainty", evidence_ids=[r["evidence_id"]]))
            if not any(s.kind == "uncertainty" for s in out):
                ev = next(s.evidence_ids for s in out if s.kind == "prediction")
                out.append(Statement(text="Model outputs are predictions with uncertainty, "
                                          "not measurements.", kind="uncertainty",
                                     evidence_ids=ev))
    out = out[:14]
    seen = {e.lower() for s in out for e in s.evidence_ids}
    bad = {v.statement for v in verify(AgentAnswer(statements=out), rows, seen)
           if v.statement is not None}
    safe = [s for i, s in enumerate(out) if i not in bad]
    if not safe or all(s.kind == "recommendation" for s in safe) and bad:
        safe.append(Statement(text="Some evidence could not be summarised safely; open the "
                                   "evidence table to read it directly.", kind="recommendation"))
    return AgentAnswer(statements=safe)
