from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from akash_core.enums import ProvRelation
from akash_core.ids import new_id


class ProvenanceRecord(BaseModel):
    """One entity or activity in the lineage graph (PROV-style)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prov_id: UUID = Field(default_factory=new_id)
    entity_type: str  # e.g. "raw_fits", "clean_lightcurve", "prediction"
    activity: str  # e.g. "fetch:mast", "preprocess:v1", "infer:transit-cnn@1.0"
    code_version: str  # git SHA or package version
    sha256: str | None = None  # content hash if the entity is an artifact
    source_uri: str | None = None
    dataset: str | None = None
    release: str | None = None
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProvenanceEdge(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    from_prov: UUID
    to_prov: UUID
    relation: ProvRelation
