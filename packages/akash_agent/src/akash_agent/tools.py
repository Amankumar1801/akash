"""Typed, read-only tools. The model never sees code, SQL, paths or URLs, only these verbs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .types import ToolSpec
from .view import InvestigationView

Channel = Literal["observed_fact", "catalog_status", "model_prediction", "anomaly",
                  "data_quality", "cross_survey", "interpretation"]
Direction = Literal["supports", "contradicts", "neutral", "inconclusive"]

GLOSSARY: dict[str, str] = {
    "known_confirmed": "A curated archive already lists a confirmed planet at this period.",
    "known_candidate": "A curated archive already lists this signal as a planet candidate.",
    "known_false_positive": "A curated archive has already ruled this signal out as a planet.",
    "new_signal_review": "No catalog match and no decisive vetting failure. A reason for a human "
                         "to look. It is not a discovery.",
    "likely_systematic": "Vetting found a failure that points away from a planet.",
    "models_disagree": "The classifiers split. The disagreement is itself informative.",
    "insufficient_data": "The data could not support a call either way.",
    "odd_even": "Odd and even transits should have the same depth. A difference suggests an "
                "eclipsing binary at twice the period.",
    "secondary_eclipse": "A planet-sized object rarely produces a visible secondary eclipse.",
    "transit_shape": "Planet transits are flat-bottomed; V-shaped dips suggest grazing eclipses.",
    "periodicity_coverage": "Enough transits must be observed to trust the period.",
    "systematics_coincidence": "Dips that line up with known instrument events are suspect.",
    "duration_plausibility": "The dip duration must be possible for the star's size and period.",
    "depth_radius": "The depth must imply a planet-sized, not star-sized, object.",
    "percentile": "How unusual the light curve is relative to a stated reference population. "
                  "Unusual does not mean a planet and does not mean a discovery.",
    "calibrated_probability": "A classifier output adjusted so that stated probabilities match "
                              "observed frequencies on held-out data.",
    "conformal_set": "A set of labels that contains the truth at the stated coverage "
                     "(here 90%) on exchangeable data.",
    "ood": "Out of distribution: the signal looks unlike the data the classifier learned from.",
}


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(_Args):
    pass


class ListEvidenceArgs(_Args):
    channel: Channel | None = None
    direction: Direction | None = None


class EvidenceIdArgs(_Args):
    evidence_id: str = Field(min_length=8, max_length=64, pattern=r"^[0-9a-fA-F-]+$")


class TermArgs(_Args):
    term: Literal[tuple(GLOSSARY)]  # type: ignore[valid-type]


@dataclass(frozen=True)
class ToolResult:
    data: Any
    seen_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[_Args]
    run: Callable[[InvestigationView, Any], ToolResult]
    read_only: bool = True


def _brief(r: dict[str, Any]) -> dict[str, Any]:
    return {"evidence_id": r["evidence_id"], "channel": r["channel"], "reads_as": r["agreement"],
            "observation": r["observation"], "reliability": r["reliability"]}


def _get_assessment(v: InvestigationView, _: NoArgs) -> ToolResult:
    a = v.assessment()
    if a is None:
        return ToolResult({"assessment": None,
                           "note": "no assessment: the signal search found nothing to assess"})
    ids: list[str] = [str(i) for r in a.get("triage_reasons", [])
                      for i in r.get("evidence_ids", [])]
    ids += [str(i) for i in a.get("conflicting_evidence", [])]
    return ToolResult(a, tuple(dict.fromkeys(ids)))


def _list_evidence(v: InvestigationView, a: ListEvidenceArgs) -> ToolResult:
    rows = [r for r in v.evidence()
            if (a.channel is None or r["channel"] == a.channel)
            and (a.direction is None or r["agreement"] == a.direction)]
    return ToolResult([_brief(r) for r in rows[:40]], tuple(r["evidence_id"] for r in rows[:40]))


def _find(v: InvestigationView, eid: str) -> dict[str, Any] | None:
    return next((r for r in v.evidence() if r["evidence_id"].lower() == eid.lower()), None)


def _get_evidence(v: InvestigationView, a: EvidenceIdArgs) -> ToolResult:
    r = _find(v, a.evidence_id)
    if r is None:
        return ToolResult({"error": "no such evidence in this investigation"})
    out = _brief(r) | {"result": r["result"], "uncertainty": r["uncertainty"],
                       "made_by": f'{r["created_by"]} {r["version"]}',
                       "source": {k: r["source"].get(k) for k in ("source", "dataset", "release")}}
    return ToolResult(out, (r["evidence_id"],))


def _get_provenance(v: InvestigationView, a: EvidenceIdArgs) -> ToolResult:
    r = _find(v, a.evidence_id)
    if r is None:
        return ToolResult({"error": "no such evidence in this investigation"})
    chain = [{"activity": n.get("activity"), "kind": n.get("entity_type"),
              "code_version": n.get("code_version"), "dataset": n.get("dataset"),
              "release": n.get("release"), "source_uri": n.get("source_uri"),
              "sha256_prefix": (n.get("sha256") or "")[:12]}
             for n in v.provenance_chain(r["evidence_id"])]
    return ToolResult({"evidence_id": r["evidence_id"], "chain": chain}, (r["evidence_id"],))


def _explain(_: InvestigationView, a: TermArgs) -> ToolResult:
    return ToolResult({"term": a.term, "definition": GLOSSARY[a.term]})


TOOLS: tuple[Tool, ...] = (
    Tool("get_assessment", "The investigation's triage category, reasons, signal summary, "
         "prediction, anomaly percentile, vetting and catalog status.", NoArgs, _get_assessment),
    Tool("list_evidence", "Brief list of evidence rows, optionally filtered by channel or by how "
         "they read (supports, contradicts, neutral, inconclusive).", ListEvidenceArgs,
         _list_evidence),
    Tool("get_evidence", "Full detail of one evidence row, including value and uncertainty.",
         EvidenceIdArgs, _get_evidence),
    Tool("get_provenance", "Where one evidence row came from: the chain of steps, code versions "
         "and data hashes.", EvidenceIdArgs, _get_provenance),
    Tool("explain_term", "Fixed definition of a triage category, vetting check or statistical "
         "term used in AKASH.", TermArgs, _explain),
)


@dataclass(frozen=True)
class ToolPolicy:
    allowed: frozenset[str] = frozenset(t.name for t in TOOLS)


class ToolError(Exception):
    """A tool call that cannot run. The message is safe to show the model."""


class ToolRegistry:
    def __init__(self, tools: tuple[Tool, ...] = TOOLS) -> None:
        for t in tools:
            if not t.read_only:  # write tools need an approval workflow that does not exist yet
                raise ValueError(f"tool {t.name!r} is not read-only; write tools are not supported")
        self._tools = {t.name: t for t in tools}

    def specs(self, policy: ToolPolicy) -> list[ToolSpec]:
        return [ToolSpec(t.name, t.description, t.args.model_json_schema())
                for t in self._tools.values() if t.name in policy.allowed]

    def call(self, name: str, args: dict[str, Any], view: InvestigationView,
             policy: ToolPolicy) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"unknown tool {name!r}")
        if name not in policy.allowed:
            raise ToolError(f"tool {name!r} is not permitted here")
        try:
            parsed = tool.args.model_validate(args)
        except ValidationError as e:
            raise ToolError("invalid arguments: " + "; ".join(
                f'{".".join(map(str, x["loc"]))}: {x["type"]}' for x in e.errors()[:3])) from None
        return tool.run(view, parsed)
