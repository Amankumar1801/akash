from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from akash_core.enums import CreatorType, Direction, EvidenceChannel, ReliabilityClass
from akash_core.ids import new_id


class Creator(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: CreatorType
    name: str
    version: str


class Evidence(BaseModel):
    """A single typed, traceable finding. Immutable; superseded, never edited."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: UUID = Field(default_factory=new_id)
    investigation_id: UUID
    channel: EvidenceChannel
    direction: Direction
    claim: str = Field(min_length=1)
    value: dict[str, Any] = Field(default_factory=dict)
    uncertainty: dict[str, Any] | None = None
    reliability: ReliabilityClass = ReliabilityClass.UNKNOWN
    provenance_ids: tuple[UUID, ...] = ()
    created_by: Creator
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    superseded_by: UUID | None = None

    @model_validator(mode="after")
    def _invariants(self) -> Evidence:
        # 1. Everything except interpretation must be traceable to provenance.
        if self.channel != EvidenceChannel.INTERPRETATION and not self.provenance_ids:
            raise ValueError(f"{self.channel.value} evidence requires provenance_ids")
        # 2. Interpretations may only come from an LLM or a human, and must cite evidence.
        if self.channel == EvidenceChannel.INTERPRETATION:
            if self.created_by.type not in (CreatorType.LLM, CreatorType.HUMAN):
                raise ValueError("interpretation must be created by an llm or a human")
            if not self.value.get("cites"):
                raise ValueError("interpretation must cite evidence ids in value['cites']")
        # 3. Catalog status must name its source.
        if self.channel == EvidenceChannel.CATALOG_STATUS and "source" not in self.value:
            raise ValueError("catalog_status evidence requires value['source']")
        # 4. LLM output can never claim archive-curated reliability.
        if (
            self.created_by.type == CreatorType.LLM
            and self.reliability != ReliabilityClass.LLM_GENERATED
        ):
            raise ValueError("llm-created evidence must have reliability=llm_generated")
        return self
