"""The agent's entire window onto the world: one investigation, read-only.

The agent can never name another investigation, a file, a URL or a table. Whatever the model
asks for, it can only ever get these three things for the investigation the caller was already
authorised to see."""

from __future__ import annotations

from typing import Any, Protocol


class InvestigationView(Protocol):
    def assessment(self) -> dict[str, Any] | None: ...
    def evidence(self) -> list[dict[str, Any]]: ...
    def provenance_chain(self, evidence_id: str) -> list[dict[str, Any]]: ...


class StaticView:
    """In-memory view, for tests, demos and offline use."""

    def __init__(self, assessment: dict[str, Any] | None, evidence: list[dict[str, Any]],
                 chains: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self._a, self._e, self._c = assessment, evidence, chains or {}

    def assessment(self) -> dict[str, Any] | None:
        return self._a

    def evidence(self) -> list[dict[str, Any]]:
        return self._e

    def provenance_chain(self, evidence_id: str) -> list[dict[str, Any]]:
        return self._c.get(evidence_id, [])
