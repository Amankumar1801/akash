"""Provider contracts. Three roles, deliberately separate:

- NameResolver:        text/coords  -> candidate objects (identity layer input)
- CatalogProvider:     object       -> catalog records (stellar params, known status)
- ObservationProvider: object       -> observation refs -> raw bytes -> normalized data
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from akash_core.enums import Modality
from akash_core.schemas import AstronomicalObject

from .lightcurve import NormalizedLightCurve


@dataclass(frozen=True)
class ProviderHealth:
    name: str
    circuit_state: str
    last_error: str | None = None


@dataclass(frozen=True)
class ObsFilter:
    segments: tuple[int, ...] | None = None  # sectors / quarters
    max_observations: int | None = None


@dataclass(frozen=True)
class ObservationRef:
    provider: str
    dataset: str  # e.g. "TESS-SPOC"
    native_obs_id: str
    modality: Modality
    url: str
    meta: dict[str, Any] = field(default_factory=dict)

    def key(self) -> str:
        return f"{self.provider}|{self.dataset}|{self.native_obs_id}"


@dataclass(frozen=True)
class FetchedArtifact:
    ref: ObservationRef
    content: bytes
    source_uri: str
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class CatalogRecord:
    source: str  # e.g. "NASA Exoplanet Archive"
    table: str
    native_id: str
    values: dict[str, Any]
    status: str | None  # normalised: confirmed | candidate | false_positive | None
    query: str  # exact query text, for provenance
    source_uri: str
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class DataProvider(Protocol):
    name: str

    def health(self) -> ProviderHealth: ...


@runtime_checkable
class CatalogProvider(DataProvider, Protocol):
    def lookup(self, obj: AstronomicalObject) -> list[CatalogRecord]: ...


@runtime_checkable
class ObservationProvider(DataProvider, Protocol):
    def list_observations(
        self, obj: AstronomicalObject, flt: ObsFilter
    ) -> list[ObservationRef]: ...
    def fetch(self, ref: ObservationRef) -> FetchedArtifact: ...
    def normalize(self, art: FetchedArtifact) -> NormalizedLightCurve: ...
