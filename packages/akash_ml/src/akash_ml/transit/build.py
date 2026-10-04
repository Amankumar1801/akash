"""Build a TransitDataset from catalog TCE records + light curves (works for any catalog)."""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from akash_core.errors import ValidationFailure
from akash_data.lightcurve import NormalizedLightCurve
from akash_science.lightcurve.ephemeris import process_ephemeris, stitch_lightcurves

from .dataset import TransitDataset
from .features import features_from_ephemeris

BKJD_OFFSET = 2454833.0
LABELS = {"PC": 1, "AFP": 0, "NTP": 0}  # Robovetter training-set dispositions; UNK is dropped
KEPLER_COLS = ("kepid", "tce_plnt_num", "tce_period", "tce_time0bk", "tce_duration",
               "av_training_set")


@dataclass(frozen=True)
class TceRecord:
    star_id: int
    tce_id: str
    label: int
    period_d: float
    t0_bjd: float
    duration_d: float


def load_kepler_dr25_csv(path: str | Path) -> list[TceRecord]:
    """Parse the NASA Exoplanet Archive Kepler DR25 TCE table (CSV, '#' comments allowed).
    Column names follow the archive documentation; the check below fails loudly if your download
    differs. NOTE: labels are Robovetter dispositions, so a model trained on them partly learns
    to imitate that pipeline, and AFP/NTP are themselves model-derived labels."""
    with open(path, newline="") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        missing = [c for c in KEPLER_COLS if c not in (rows.fieldnames or [])]
        if missing:
            raise ValidationFailure(f"TCE table missing columns {missing}; got {rows.fieldnames}")
        out = []
        for r in rows:
            lab = LABELS.get(r["av_training_set"].strip())
            if lab is None:
                continue
            try:
                kic, n = int(r["kepid"]), int(r["tce_plnt_num"])
                out.append(TceRecord(kic, f"{kic}.{n:02d}", lab, float(r["tce_period"]),
                                     float(r["tce_time0bk"]) + BKJD_OFFSET,
                                     float(r["tce_duration"]) / 24.0))  # hours -> days
            except ValueError:
                continue  # blank/NaN ephemeris
    return out


def build_dataset(records: list[TceRecord],
                  get_lightcurves: Callable[[int], list[NormalizedLightCurve]],
                  skipped: list[tuple[str, str]] | None = None) -> TransitDataset:
    """Group records by star so each star's light curves are fetched/stitched once."""
    skipped = skipped if skipped is not None else []
    by_star: dict[int, list[TceRecord]] = {}
    for r in records:
        by_star.setdefault(r.star_id, []).append(r)
    rows = []
    for star, recs in by_star.items():
        try:
            lc = stitch_lightcurves(get_lightcurves(star))
        except Exception as e:  # noqa: BLE001  (one bad star must not kill a 100k-row build)
            skipped += [(r.tce_id, f"light curve unavailable: {e}") for r in recs]
            continue
        for r in recs:
            res = process_ephemeris(lc, r.period_d, r.t0_bjd, r.duration_d)
            if res is None:
                skipped.append((r.tce_id, "insufficient usable data at ephemeris"))
                continue
            rows.append((r, res))
    if not rows:
        raise ValidationFailure("no TCEs could be processed")
    return TransitDataset(
        np.array([r.tce_id for r, _ in rows]),
        np.array([r.star_id for r, _ in rows], dtype=np.int64),
        np.array([r.label for r, _ in rows], dtype=np.int8),
        np.stack([x.global_view for _, x in rows]).astype(np.float32),
        np.stack([x.local_view for _, x in rows]).astype(np.float32),
        np.stack([features_from_ephemeris(x) for _, x in rows]),
        {"snr": np.array([x.tce.snr for _, x in rows]),
         "period_d": np.array([r.period_d for r, _ in rows]),
         "depth_ppm": np.array([x.tce.depth_ppm for _, x in rows])})


def lightcurve_getter(
    resolve: Callable[[int], object], ingest: Callable[[object], list[Any]],
    load_normalized: Callable[[object], NormalizedLightCurve],
) -> Callable[[int], list[NormalizedLightCurve]]:
    """Adapter from the Phase 1 data layer to `build_dataset`: star id -> its light curves.

    resolve(star_id) -> canonical object; ingest(obj) -> observations (cached/idempotent);
    load_normalized(obs) -> NormalizedLightCurve. Kept as injected callables so this logic is
    testable without any network."""
    def get(star_id: int) -> list[NormalizedLightCurve]:
        obs = ingest(resolve(star_id))
        if not obs:
            raise ValidationFailure(f"no light curves ingested for star {star_id}")
        return [load_normalized(o) for o in obs]
    return get
