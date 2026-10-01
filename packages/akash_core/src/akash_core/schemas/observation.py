from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from akash_core.enums import Modality
from akash_core.ids import new_id


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    obs_id: UUID = Field(default_factory=new_id)
    object_id: UUID
    dataset: str  # e.g. "TESS-SPOC"
    release: str | None = None
    native_obs_id: str  # the archive's own identifier
    modality: Modality
    mission_meta: dict[str, str | float | int | None] = Field(default_factory=dict)
    artifact_ids: list[UUID] = Field(default_factory=list)
    provenance_id: UUID
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
