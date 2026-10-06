"""The Evidence Matrix: one row per finding with source, result, reliability, agreement,
timestamp/version and provenance. Components are NOT collapsed into a score."""

from __future__ import annotations

from typing import Any

from akash_core.schemas import Evidence
from akash_provenance import SqliteProvenanceStore


def _root(prov: SqliteProvenanceStore, e: Evidence) -> dict[str, Any]:
    if not e.provenance_ids:
        return {"source": "AKASH interpretation (LLM/human)", "uri": None, "dataset": None,
                "release": None, "sha256": None}
    first = prov.get(e.provenance_ids[0])
    chain = [first, *prov.lineage(first.prov_id)]
    roots = [r for r in chain if r.source_uri] or chain[-1:]
    r = roots[0]
    return {"source": r.dataset or r.activity, "activity": r.activity, "uri": r.source_uri,
            "dataset": r.dataset,
            "release": r.release, "sha256": r.sha256}


def evidence_matrix(evidence: list[Evidence], prov: SqliteProvenanceStore) -> list[dict[str, Any]]:
    rows = []
    for e in evidence:
        src = _root(prov, e)
        rows.append({
            "evidence_id": str(e.evidence_id), "channel": e.channel.value,
            "observation": e.claim, "result": e.value, "uncertainty": e.uncertainty,
            "reliability": e.reliability.value, "agreement": e.direction.value,
            "timestamp": e.created_at.isoformat(),
            "version": (e.created_by.version if e.created_by.version.startswith(e.created_by.name)
                        else f"{e.created_by.name}@{e.created_by.version}"),
            "created_by": e.created_by.type.value, "source": src,
            "provenance_ids": [str(p) for p in e.provenance_ids]})
    return rows
