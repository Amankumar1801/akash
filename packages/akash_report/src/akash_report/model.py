"""The report as data. Rendering is a separate, dumb step, so what is rendered is what is stored."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# fact: measured or catalogued. prediction: a model output. interpretation: written by an LLM or a
# human and cited. uncertainty / limitation / followup / note: framing, never evidence.
BlockKind = Literal["fact", "prediction", "interpretation", "uncertainty", "limitation",
                    "followup", "note"]

DISCLAIMER = "AKASH assists investigation; it does not independently establish discoveries."


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Block(_M):
    kind: BlockKind
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    author: str | None = None  # set on interpretations: who wrote it (llm / human)


class Section(_M):
    number: int
    id: str
    title: str
    blocks: list[Block]


class ProvRef(_M):
    evidence_id: str
    channel: str
    source: str | None
    dataset: str | None
    release: str | None
    produced_by: str
    reliability: str
    sha256_prefix: str | None


class Report(_M):
    investigation_id: str
    object_name: str
    triage_category: str | None
    pipeline_version: str
    generated_at: str
    disclaimer: str = DISCLAIMER
    sections: list[Section]
    provenance: list[ProvRef]
    provenance_verifiable: bool | None
    withheld: int = 0  # blocks removed because their text broke a wording rule
    content_sha256: str = ""  # over everything except generated_at, so reruns are comparable
