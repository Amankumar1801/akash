"""Builds the report from stored data only. No model is involved, so nothing can be invented.

Rules: every non-framing block cites evidence ids that exist in this investigation; facts,
predictions and interpretations are kept in separate sections or clearly typed; text from outside
(catalogs, headers) is cleaned and redacted if it looks like instructions; wording that asserts a
discovery or certainty is withheld and counted."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from akash_agent.guard import REDACTED, clean_text, looks_like_injection
from akash_agent.verify import forbidden_wording

from .model import Block, ProvRef, Report, Section

FACT_CH = ("observed_fact", "data_quality")
LIMITS = (
    "Light curves are a single photometric band and cannot by themselves distinguish a planet "
    "from every astrophysical false positive.",
    "Classifier probabilities describe resemblance to the training data. They are not the "
    "probability that the object is a planet.",
    "An anomaly percentile is relative to the named reference population and says nothing about "
    "cause.",
    "Catalog status reflects the archive at the time of retrieval and may have changed.",
    "Results are reproducible only with the code versions and data hashes in section 13.",
)


def _safe(text: str, n: int = 500) -> str:
    t = clean_text(str(text), n).strip()
    return REDACTED if looks_like_injection(t) else t


class _Builder:
    def __init__(self, evidence: list[dict[str, Any]]) -> None:
        self.rows = {r["evidence_id"]: r for r in evidence}
        self.withheld = 0

    def block(self, kind: str, text: str, ids: list[str] | None = None,
              author: str | None = None) -> Block | None:
        text = _safe(text)
        ids = [i for i in (ids or []) if i in self.rows]
        if forbidden_wording(text):
            self.withheld += 1
            return None
        return Block(kind=kind, text=text, evidence_ids=ids, author=author)

    def from_rows(self, kind: str, rows: list[dict[str, Any]]) -> list[Block]:
        out = []
        for r in rows:
            note = {"supports": "supports a planetary origin",
                    "contradicts": "argues against a planetary origin",
                    "inconclusive": "is inconclusive"}.get(r["agreement"])
            text = r["observation"].rstrip(".") + (f" ({note})" if note else "")
            b = self.block(kind, text, [r["evidence_id"]])
            if b:
                out.append(b)
        return out


def _by(evidence: list[dict[str, Any]], *channels: str) -> list[dict[str, Any]]:
    return [r for r in evidence if r["channel"] in channels]


def build_report(*, investigation_id: str, object_name: str, object_info: dict[str, Any],
                 assessment: dict[str, Any] | None, evidence: list[dict[str, Any]],
                 prov_verifiable: bool | None, pipeline_version: str,
                 generated_at: str) -> Report:
    b = _Builder(evidence)
    a = assessment or {}
    S: list[Section] = []

    def sec(id_: str, title: str, blocks: Sequence[Block | None]) -> None:
        bl = [x for x in blocks if x]
        S.append(Section(number=len(S) + 1, id=id_, title=title, blocks=bl or [
            Block(kind="note", text="Nothing was recorded for this section.")]))

    # 1 overview
    cat = a.get("triage_category")
    ov: list[Block | None] = [b.block("note", f"Object: {object_name}. "
                                      f"Position RA {object_info.get('ra_deg', float('nan')):.4f}, "
                                      f"Dec {object_info.get('dec_deg', float('nan')):.4f} deg.")]
    if cat:
        ids = [i for r in a.get("triage_reasons", []) for i in r.get("evidence_ids", [])]
        ov.append(b.block("note", f"Triage category: {str(cat).replace('_', ' ')}. This is a rule-"
                                  "based reason for a human to look, not a conclusion about the "
                                  "object.", [str(i) for i in ids]))
    else:
        ov.append(b.block("note", "No assessment exists: the signal search found no repeating dip "
                                  "it could defend. That says this data holds no detectable "
                                  "periodic signal, not that the star has no planets."))
    sec("overview", "Object overview", ov)

    # 2 data sources
    seen: dict[tuple[Any, ...], list[str]] = {}
    for r in evidence:
        s = r["source"]
        seen.setdefault((s.get("source"), s.get("dataset"), s.get("release")), []).append(
            r["evidence_id"])
    sec("data_sources", "Data sources", [
        b.block("fact", f"{k[0] or 'unknown source'}, dataset {k[1] or 'n/a'}, release "
                        f"{k[2] or 'n/a'}", ids[:12]) for k, ids in seen.items()])

    sec("observational", "Observational evidence", b.from_rows("fact", _by(evidence, *FACT_CH)))

    pred = a.get("prediction")
    ml: list[Block | None] = [*b.from_rows("prediction", _by(evidence, "model_prediction"))]
    if pred:
        ids = [r["evidence_id"] for r in _by(evidence, "model_prediction")]
        lo, hi = pred["interval_90"]
        cal = "calibrated" if pred["calibrated"] else "not calibrated"
        ml.append(b.block(
            "prediction", f"Planet-like probability {pred['planet_like_probability']:.2f}, "
            f"90% interval {lo:.2f} to {hi:.2f}; {cal}.", ids))
        d = pred.get("disagreement")
        if d and d["flag"]:
            ml.append(b.block("prediction", "The classifiers disagree with each other "
                              f"(spread {d['range']:.2f}).", ids))
    sec("ml", "ML predictions", ml)

    an = a.get("anomaly")
    anl: list[Block | None] = [*b.from_rows("prediction", _by(evidence, "anomaly"))]
    if an:
        aids = [r["evidence_id"] for r in _by(evidence, "anomaly")]
        anl.append(b.block(
            "prediction", f"Anomaly percentile {an['percentile']:.0f} against "
            f"{an['reference_population']} (category {an['category']}). Unusual does not mean "
            "a planet.", aids))
    sec("anomaly", "Anomaly analysis", anl)

    sec("cross", "Cross-survey evidence",
        b.from_rows("fact", _by(evidence, "catalog_status", "cross_survey")))

    drivers = (an or {}).get("drivers") or []
    sec("explain", "Explainability", [
        b.block("prediction", f"Feature {d.get('feature', d.get('name', '?'))} contributed "
                f"{d.get('contribution', d.get('value', ''))}",
                [r["evidence_id"] for r in _by(evidence, "anomaly")]) for d in drivers[:8]]
        or [b.block("note", "No per-feature attribution was recorded for this investigation.")])

    unc: list[Block | None] = []
    if pred:
        unc.append(b.block("uncertainty", "Probability uncertainty is the stated 90% interval; "
                           "model versions: " + ", ".join(pred["model_versions"]) + ".",
                           [r["evidence_id"] for r in _by(evidence, "model_prediction")]))
    ood = a.get("ood")
    if ood:
        msg = ("The signal looks unlike the training data (out of distribution), so model "
               "outputs are less reliable." if ood["flag"]
               else "The signal is within the range of the training data.")
        unc.append(b.block("uncertainty", msg,
                           [r["evidence_id"] for r in _by(evidence, "model_prediction")]))
    dq = a.get("data_quality")
    if dq:
        unc.append(b.block("uncertainty", f"Data quality grade {dq['grade']}"
                           + (": " + "; ".join(dq["reasons"]) if dq["reasons"] else "") + ".",
                           [r["evidence_id"] for r in _by(evidence, "data_quality")]))
    for r in evidence:
        if r.get("uncertainty") and r["channel"] in ("observed_fact",):
            unc.append(b.block("uncertainty", "Stated uncertainty for: " + r["observation"],
                               [r["evidence_id"]]))
    sec("uncertainty", "Uncertainty", unc)

    interp = [x for x in _by(evidence, "interpretation")]
    sec("interpretations", "Possible interpretations (written by an LLM or a person, not measured)",
        [b.block("interpretation", r["observation"], [r["evidence_id"]],
                 author=str(r["created_by"])) for r in interp]
        or [b.block("note", "No interpretation has been recorded. Nothing in this report is an "
                            "AI-generated reading of the data.")])

    conf_ids = {str(i) for i in a.get("conflicting_evidence", [])}
    conf = [r for r in evidence if r["agreement"] == "contradicts" or r["evidence_id"] in conf_ids]
    sec("conflicts", "Conflicting evidence", b.from_rows("fact", conf)
        or [b.block("note", "No recorded evidence contradicts the supporting evidence.")])

    sec("limitations", "Limitations", [b.block("limitation", t) for t in LIMITS])
    sec("followup", "Recommended follow-up", [b.block("followup", t)
                                              for t in a.get("recommended_followup", [])])

    prov = [ProvRef(
        evidence_id=r["evidence_id"], channel=r["channel"], source=r["source"].get("source"),
        dataset=r["source"].get("dataset"), release=r["source"].get("release"),
        produced_by=f'{r["created_by"]} {r["version"]}', reliability=r["reliability"],
        sha256_prefix=((r["source"].get("sha256") or "")[:12] or None)) for r in evidence]
    verdict = "not verified" if prov_verifiable is None else ("yes" if prov_verifiable else "NO")
    sec("provenance", "References and data provenance", [
        b.block("note", f"Provenance chain verifiable: {verdict}. {len(prov)} evidence rows; "
                "each is listed below with its source and producer.")])

    rep = Report(investigation_id=investigation_id, object_name=_safe(object_name, 120),
                 triage_category=str(cat) if cat else None, pipeline_version=pipeline_version,
                 generated_at=generated_at, sections=S, provenance=prov,
                 provenance_verifiable=prov_verifiable, withheld=b.withheld)
    body = rep.model_dump(mode="json", exclude={"generated_at", "content_sha256"})
    rep.content_sha256 = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return rep
