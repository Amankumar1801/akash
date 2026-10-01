"""Ingestion service: object -> observations, with caching, validation and provenance.

Guarantees:
- every stored artifact has a provenance chain rooted in a fetch (source_uri + sha256)
- already-ingested observations are skipped without any download (idempotent)
- one failing/corrupt file never aborts the batch; failures are reported, bad files quarantined
"""

from __future__ import annotations

from dataclasses import dataclass, field

from akash_core.enums import ProvRelation
from akash_core.errors import AkashError, ProviderError, ValidationFailure
from akash_core.schemas import AstronomicalObject, Observation, ProvenanceRecord
from akash_provenance import SqliteProvenanceStore

from .base import ObservationProvider, ObservationRef, ObsFilter
from .lightcurve import NORMALIZER_VERSION
from .storage import ArtifactRef, LocalArtifactStore, MetadataRepo
from .validation import validate_lightcurve

REF_CACHE_TTL_S = 24 * 3600


@dataclass
class IngestResult:
    observations: list[Observation] = field(default_factory=list)
    skipped_existing: int = 0
    quarantined: list[tuple[str, str]] = field(default_factory=list)  # (native_obs_id, reason)
    errors: list[tuple[str, str]] = field(default_factory=list)
    warnings: dict[str, list[str]] = field(default_factory=dict)


class ObservationService:
    def __init__(
        self, provider: ObservationProvider, artifacts: LocalArtifactStore,
        repo: MetadataRepo, prov: SqliteProvenanceStore, code_version: str,
    ) -> None:
        self.provider, self.artifacts, self.repo, self.prov = provider, artifacts, repo, prov
        self.code_version = code_version

    def _list(self, obj: AstronomicalObject, flt: ObsFilter) -> list[ObservationRef]:
        key = f"{obj.object_id}|{flt.segments}|{flt.max_observations}"
        cached = self.repo.cache_get(self.provider.name, key, REF_CACHE_TTL_S)
        if isinstance(cached, list):
            from akash_core.enums import Modality
            return [ObservationRef(**{**c, "modality": Modality(c["modality"])}) for c in cached]
        refs = self.provider.list_observations(obj, flt)
        self.repo.cache_put(self.provider.name, key, [
            {**r.__dict__, "modality": r.modality.value} for r in refs])
        return refs

    def ingest(self, obj: AstronomicalObject, flt: ObsFilter | None = None) -> IngestResult:
        flt = flt or ObsFilter()
        res = IngestResult()
        for ref in self._list(obj, flt):
            if (existing := self.repo.find_observation(
                    obj.object_id, ref.dataset, ref.native_obs_id)):
                res.observations.append(existing)
                res.skipped_existing += 1
                continue
            try:
                obs, warns = self._ingest_one(obj, ref)
            except (ProviderError, ValidationFailure) as e:
                kind = res.quarantined if isinstance(e, ValidationFailure) else res.errors
                kind.append((ref.native_obs_id, str(e)))
                continue
            res.observations.append(obs)
            if warns:
                res.warnings[ref.native_obs_id] = warns
        return res

    def _ingest_one(
        self, obj: AstronomicalObject, ref: ObservationRef
    ) -> tuple[Observation, list[str]]:
        art = self.provider.fetch(ref)
        raw = self.artifacts.put(art.content, kind="raw_fits")
        try:
            lc = self.provider.normalize(art)
            report = validate_lightcurve(lc)
            release = lc.meta.get("data_rel")
        except ValidationFailure as e:
            self._record_raw(raw, ref, art.source_uri, None)
            self.artifacts.quarantine(raw.sha256, str(e))
            raise
        raw_prov = self._record_raw(raw, ref, art.source_uri, release)
        if not report.ok:
            self.artifacts.quarantine(raw.sha256, "; ".join(report.errors))
            raise ValidationFailure("; ".join(report.errors))

        npz = self.artifacts.put(lc.to_npz_bytes(), kind="normalized_lightcurve")
        norm_prov = self.prov.add(ProvenanceRecord(
            entity_type="normalized_lightcurve", activity=f"normalize:{NORMALIZER_VERSION}",
            code_version=self.code_version, sha256=npz.sha256, dataset=ref.dataset,
            release=release))
        self.prov.link(norm_prov.prov_id, raw_prov.prov_id, ProvRelation.WAS_DERIVED_FROM)
        self.prov.verify_chain(norm_prov.prov_id)

        obs = Observation(
            object_id=obj.object_id, dataset=ref.dataset, release=release,
            native_obs_id=ref.native_obs_id, modality=ref.modality,
            mission_meta={k: v for k, v in lc.meta.items()
                          if isinstance(v, (str, int, float)) or v is None},
            artifact_ids=[raw.artifact_id, npz.artifact_id], provenance_id=norm_prov.prov_id,
        )
        self.repo.save_observation(obs)
        return obs, report.warnings

    def _record_raw(
        self, raw: ArtifactRef, ref: ObservationRef, uri: str, release: str | None
    ) -> ProvenanceRecord:
        return self.prov.add(ProvenanceRecord(
            entity_type="raw_fits", activity=f"fetch:{self.provider.name}",
            code_version=self.code_version, sha256=raw.sha256, source_uri=uri,
            dataset=ref.dataset, release=release))


__all__ = ["AkashError", "IngestResult", "ObservationService"]
