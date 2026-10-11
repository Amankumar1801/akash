"""Typed request/response models. Requests forbid unknown fields and bound every size."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Mission = Literal["kepler", "tess"]
Mode = Literal["quick", "deep"]


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ObjectSearchRequest(_Req):
    query: Annotated[str, Field(min_length=1, max_length=120)]


class AliasOut(BaseModel):
    namespace: str
    identifier: str


class ObjectOut(BaseModel):
    object_id: UUID
    canonical_name: str
    ra_deg: float
    dec_deg: float
    anchor_namespace: str
    aliases: list[AliasOut]


class ObservationOut(BaseModel):
    obs_id: UUID
    dataset: str
    release: str | None
    native_obs_id: str
    modality: str
    segment: int | None
    retrieved_at: str


class LightCurveDataOut(BaseModel):
    obs_id: UUID
    n_total: int
    n_returned: int
    downsampled: bool
    time_bjd: list[float]
    flux: list[float | None]
    quality_flagged: list[bool]


class InvestigationRequest(_Req):
    object_id: UUID | None = None
    query: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    mission: Mission = "tess"
    mode: Mode = "deep"
    segments: Annotated[list[Annotated[int, Field(ge=0, le=500)]], Field(max_length=40)] = []
    max_observations: Annotated[int, Field(ge=1, le=40)] = 10

    @model_validator(mode="after")
    def _exactly_one_target(self) -> InvestigationRequest:
        if (self.object_id is None) == (self.query is None):
            raise ValueError("provide exactly one of object_id or query")
        return self


class JobOut(BaseModel):
    investigation_id: UUID
    status: str
    created_at: float
    started_at: float | None
    finished_at: float | None
    error: str | None
    outcome: str | None
    category: str | None
    cancel_requested: bool
    deduplicated: bool = False
    links: dict[str, str] = {}


class InvestigationOut(JobOut):
    object_id: UUID | None = None
    assessment: dict[str, Any] | None = None
    n_evidence: int | None = None


class EventOut(BaseModel):
    seq: int
    ts: float
    kind: str
    data: dict[str, Any]


class ProvNode(BaseModel):
    prov_id: UUID
    entity_type: str
    activity: str
    code_version: str
    sha256: str | None
    source_uri: str | None
    dataset: str | None
    release: str | None
    at: str


class ProvEdge(BaseModel):
    from_prov: UUID
    to_prov: UUID
    relation: str


class ProvenanceGraphOut(BaseModel):
    nodes: list[ProvNode]
    edges: list[ProvEdge]
    roots_verifiable: bool


class ModelOut(BaseModel):
    name: str
    version: str
    created_at: str | None
    feature_version: str | None
    data_hash: str | None
    n: dict[str, int] | None = None


class MeOut(BaseModel):
    name: str
    role: str
    key_id: str
