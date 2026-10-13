"""Adapts one authorised investigation's stored data to the agent's read-only view."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from akash_fusion.matrix import evidence_matrix

from .db import StoreContext


class ApiInvestigationView:
    def __init__(self, ctx: StoreContext, investigation_id: UUID) -> None:
        self._ctx, self._id = ctx, investigation_id
        self._rows: list[dict[str, Any]] | None = None

    def assessment(self) -> dict[str, Any] | None:
        a = self._ctx.evidence.get_assessment(self._id)
        return a.model_dump(mode="json") if a else None

    def evidence(self) -> list[dict[str, Any]]:
        if self._rows is None:
            self._rows = evidence_matrix(self._ctx.evidence.list_evidence(self._id), self._ctx.prov)
        return self._rows

    def provenance_chain(self, evidence_id: str) -> list[dict[str, Any]]:
        row = next((r for r in self.evidence() if r["evidence_id"] == evidence_id), None)
        if row is None or not row["provenance_ids"]:
            return []
        first = UUID(row["provenance_ids"][0])
        nodes = [self._ctx.prov.get(first), *self._ctx.prov.lineage(first)]
        return [{"activity": n.activity, "entity_type": n.entity_type,
                 "code_version": n.code_version, "dataset": n.dataset, "release": n.release,
                 "source_uri": n.source_uri, "sha256": n.sha256} for n in nodes]
