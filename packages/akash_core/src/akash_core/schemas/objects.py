from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from akash_core.ids import new_id


class ObjectAlias(BaseModel):
    """(namespace, identifier) is globally unique, e.g. ('TIC', '261136679')."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    namespace: str
    identifier: str
    source: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("namespace")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class AstronomicalObject(BaseModel):
    """Canonical internal object. Position is ICRS degrees at the stated epoch."""

    model_config = ConfigDict(extra="forbid")

    object_id: UUID = Field(default_factory=new_id)
    ra_deg: float = Field(ge=0.0, lt=360.0)
    dec_deg: float = Field(ge=-90.0, le=90.0)
    epoch: float = 2000.0
    pm_ra_mas_yr: float | None = None
    pm_dec_mas_yr: float | None = None
    parallax_mas: float | None = None
    canonical_name: str
    anchor_namespace: str = "GAIA_DR3"
    aliases: list[ObjectAlias] = Field(default_factory=list)

    def alias(self, namespace: str) -> str | None:
        ns = namespace.upper()
        return next((a.identifier for a in self.aliases if a.namespace == ns), None)
