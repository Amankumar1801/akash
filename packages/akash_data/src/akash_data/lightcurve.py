"""Normalized light-curve container and SPOC/Kepler FITS parsing.

Time is stored as absolute BJD (TDB). Native quality flags are preserved verbatim;
mapping them to a shared enum is deliberately deferred to the Phase 2 quality filter.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from akash_core.errors import ValidationFailure
from astropy.io import fits

NORMALIZER_VERSION = "spoc-normalize@1"


@dataclass
class NormalizedLightCurve:
    time_bjd: np.ndarray  # float64, absolute BJD-TDB, finite, sorted
    flux: np.ndarray  # float64, PDCSAP (may contain NaN where flagged)
    flux_err: np.ndarray
    sap_flux: np.ndarray
    native_quality: np.ndarray  # int32, mission bitmask, untouched
    meta: dict[str, Any] = field(default_factory=dict)

    def to_npz_bytes(self) -> bytes:
        buf = io.BytesIO()
        np.savez_compressed(
            buf,
            time_bjd=self.time_bjd, flux=self.flux, flux_err=self.flux_err,
            sap_flux=self.sap_flux, native_quality=self.native_quality,
            meta=np.frombuffer(json.dumps(self.meta, sort_keys=True).encode(), dtype=np.uint8),
        )
        return buf.getvalue()

    @classmethod
    def from_npz_bytes(cls, data: bytes) -> NormalizedLightCurve:
        z = np.load(io.BytesIO(data), allow_pickle=False)  # never allow pickle
        return cls(
            z["time_bjd"], z["flux"], z["flux_err"], z["sap_flux"], z["native_quality"],
            json.loads(z["meta"].tobytes().decode()),
        )


@dataclass(frozen=True)
class MissionSpec:
    name: str
    id_key: str  # primary-header key holding the target id
    segment_key: str  # SECTOR / QUARTER
    required_primary: tuple[str, ...]
    required_table: tuple[str, ...] = ("TIME", "PDCSAP_FLUX", "PDCSAP_FLUX_ERR", "SAP_FLUX")
    # The quality bitmask column is named differently per mission: TESS files call it QUALITY,
    # Kepler files call it SAP_QUALITY. The first name present in the file is used.
    quality_cols: tuple[str, ...] = ("QUALITY",)


TESS = MissionSpec("TESS", "TICID", "SECTOR", ("OBJECT", "TICID", "SECTOR", "RA_OBJ", "DEC_OBJ"))
KEPLER = MissionSpec(
    "Kepler", "KEPLERID", "QUARTER", ("OBJECT", "KEPLERID", "QUARTER", "RA_OBJ", "DEC_OBJ"),
    quality_cols=("SAP_QUALITY", "QUALITY"),
)
MISSIONS = {"TESS": TESS, "Kepler": KEPLER}


def _f64(col: Any) -> np.ndarray:
    return np.array(col, dtype=np.float64)  # converts FITS big-endian to native


def parse_lightcurve_fits(content: bytes, mission: MissionSpec) -> NormalizedLightCurve:
    try:
        hdul = fits.open(io.BytesIO(content), memmap=False)
    except Exception as e:  # astropy raises many types for malformed files
        raise ValidationFailure(f"not a readable FITS file: {e}") from e
    with hdul:
        if len(hdul) < 2:
            raise ValidationFailure("FITS has no table extension")
        ph, th = hdul[0].header, hdul[1].header
        missing = [k for k in mission.required_primary if k not in ph]
        if missing:
            raise ValidationFailure(f"missing primary header keys: {missing}")
        data = hdul[1].data
        names = set(data.columns.names)
        miss_cols = [c for c in mission.required_table if c not in names]
        qcol = next((c for c in mission.quality_cols if c in names), None)
        if qcol is None:
            miss_cols.append("/".join(mission.quality_cols))
        if miss_cols:
            raise ValidationFailure(f"missing table columns: {miss_cols}")
        assert qcol is not None
        if str(th.get("TIMESYS", "")).strip().upper() != "TDB":
            raise ValidationFailure(f"unexpected TIMESYS {th.get('TIMESYS')!r}, expected TDB")
        if "BJDREFI" not in th:
            raise ValidationFailure("missing BJDREFI in table header")

        ref = float(th["BJDREFI"]) + float(th.get("BJDREFF", 0.0))
        t = _f64(data["TIME"])
        keep = np.isfinite(t)
        n_dropped = int((~keep).sum())
        order = np.argsort(t[keep], kind="stable")

        def col(name: str) -> np.ndarray:
            return _f64(data[name])[keep][order]

        quality = np.array(data[qcol], dtype=np.int64)[keep][order].astype(np.int32)
        meta = {
            "mission": mission.name,
            "object": str(ph["OBJECT"]).strip(),
            "target_id": int(ph[mission.id_key]),
            "segment": int(ph[mission.segment_key]),
            "ra_obj": float(ph["RA_OBJ"]),
            "dec_obj": float(ph["DEC_OBJ"]),
            "data_rel": str(ph.get("DATA_REL", "")) or None,
            "camera": ph.get("CAMERA"),
            "ccd": ph.get("CCDNUM", ph.get("CHANNEL")),
            "mag": ph.get("TESSMAG", ph.get("KEPMAG")),
            "flux_kind": "PDCSAP_FLUX",
            "bjdref": ref,
            "rows_dropped_nonfinite_time": n_dropped,
            "normalizer": NORMALIZER_VERSION,
        }
        return NormalizedLightCurve(
            time_bjd=t[keep][order] + ref,
            flux=col("PDCSAP_FLUX"), flux_err=col("PDCSAP_FLUX_ERR"), sap_flux=col("SAP_FLUX"),
            native_quality=quality, meta=meta,
        )
