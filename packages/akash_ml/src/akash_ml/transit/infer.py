"""Bridge from search results (BLS TCEs) to the classifier: build one-row-per-TCE datasets."""

from __future__ import annotations

import numpy as np
from akash_science.lightcurve.ephemeris import EphemerisResult
from akash_science.lightcurve.pipeline import PipelineResult, TCEResult

from .dataset import TransitDataset
from .features import features_from_ephemeris


def ephemeris_result_from_pipeline(res: PipelineResult, tr: TCEResult) -> EphemerisResult:
    """View a search-found TCE as an EphemerisResult so the same feature code applies."""
    n_points = len(res.time)
    return EphemerisResult(tr.tce, tr.vetting, tr.global_view, tr.local_view, res.sigma,
                           res.noise_1h_ppm, res.counts, n_points)


def dataset_from_results(results: list[EphemerisResult], star_id: int = 0,
                         ids: list[str] | None = None) -> TransitDataset:
    """Unlabelled dataset (labels are placeholders) for inference only."""
    n = len(results)
    return TransitDataset(
        tce_ids=np.array(ids or [f"{star_id}.{i + 1}" for i in range(n)]),
        star_ids=np.full(n, star_id, dtype=np.int64), labels=np.zeros(n, dtype=np.int8),
        global_views=np.stack([r.global_view for r in results]).astype(np.float32),
        local_views=np.stack([r.local_view for r in results]).astype(np.float32),
        features=np.stack([features_from_ephemeris(r) for r in results]),
        meta={"snr": np.array([r.tce.snr for r in results]),
              "period_d": np.array([r.tce.period_d for r in results]),
              "depth_ppm": np.array([r.tce.depth_ppm for r in results])})
