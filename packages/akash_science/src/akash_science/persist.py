"""Persist pipeline outputs as immutable artifacts, provenance derived from the input chain."""

from __future__ import annotations

import io
import json
import math
from typing import Any
from uuid import UUID

import numpy as np
from akash_core.enums import ProvRelation
from akash_core.schemas import ProvenanceRecord
from akash_data.storage import ArtifactRef, LocalArtifactStore
from akash_provenance import SqliteProvenanceStore

from .lightcurve.pipeline import PipelineResult


def _clean(x: Any) -> Any:
    if isinstance(x, float) and not math.isfinite(x):
        return None  # strict JSON: no NaN/Inf
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


def result_to_json(res: PipelineResult) -> dict[str, Any]:
    out: dict[str, Any] = _clean({
        "version": res.version, "config_hash": res.config_hash, "sigma": res.sigma,
        "noise_1h_ppm": res.noise_1h_ppm, "counts": res.counts,
        "segments": [list(s) for s in res.segments], "warnings": res.warnings,
        "tces": [{
            "tce": {
                "rank": r.tce.rank, "period_d": r.tce.period_d,
                "period_interval_d": list(r.tce.period_interval_d), "t0_bjd": r.tce.t0_bjd,
                "duration_d": r.tce.duration_d, "depth_ppm": r.tce.depth_ppm, "snr": r.tce.snr,
                "sde": r.tce.sde, "beta": r.tce.beta, "n_transits": r.tce.n_transits,
                "transit_times_bjd": r.tce.transit_times_bjd,
            },
            "vetting": [{"name": v.name, "status": v.status.value, "summary": v.summary,
                         "metrics": v.metrics} for v in r.vetting],
        } for r in res.tces],
    })
    return out


def persist_result(
    res: PipelineResult, parent_prov_id: UUID, artifacts: LocalArtifactStore,
    prov: SqliteProvenanceStore, code_version: str,
) -> tuple[ProvenanceRecord, ArtifactRef, ArtifactRef]:
    """Returns (provenance record, JSON summary artifact, clean-arrays npz artifact)."""
    buf = io.BytesIO()
    np.savez_compressed(buf, time=res.time, flux_norm=res.flux_norm, trend=res.trend,
                        flux_detrended=res.flux_detrended)
    npz = artifacts.put(buf.getvalue(), kind="clean_lightcurve")
    js = artifacts.put(json.dumps(result_to_json(res), sort_keys=True, allow_nan=False).encode(),
                       kind="lc_pipeline_summary")
    rec = prov.add(ProvenanceRecord(
        entity_type="lc_pipeline_result", activity=f"{res.version}:{res.config_hash[:12]}",
        code_version=code_version, sha256=js.sha256))
    prov.link(rec.prov_id, parent_prov_id, ProvRelation.WAS_DERIVED_FROM)
    prov.verify_chain(rec.prov_id)
    return rec, js, npz
