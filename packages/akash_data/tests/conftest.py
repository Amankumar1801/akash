from __future__ import annotations

import io
import json
import sqlite3
from collections.abc import Callable

import httpx
import numpy as np
import pytest
from akash_data.http import CircuitBreaker, ResilientClient
from akash_data.storage import LocalArtifactStore, MetadataRepo
from akash_provenance import SqliteProvenanceStore
from astropy.io import fits


def make_fits(
    mission="TESS", n=500, cadence_s=120.0, seg=1, ident=261136679, nan_time=3,
    quality_bad_frac=0.0, shuffle=False, drop_key=None, timesys="TDB", rel="DR27",
) -> bytes:
    rng = np.random.default_rng(42)
    t = np.arange(n) * cadence_s / 86400.0 + 1325.0
    if shuffle:
        t = t[::-1].copy()
    t[:nan_time] = np.nan
    flux = 1000.0 + rng.normal(0, 1, n)
    q = np.zeros(n, dtype=np.int32)
    q[: int(n * quality_bad_frac)] = 1
    cols = [
        fits.Column("TIME", "D", array=t),
        fits.Column("SAP_FLUX", "E", array=flux * 1.01),
        fits.Column("PDCSAP_FLUX", "E", array=flux),
        fits.Column("PDCSAP_FLUX_ERR", "E", array=np.full(n, 1.0)),
        fits.Column("QUALITY" if mission == "TESS" else "SAP_QUALITY", "J", array=q),
    ]
    tab = fits.BinTableHDU.from_columns(cols)
    tab.header["TIMESYS"], tab.header["BJDREFF"] = timesys, 0.0
    tab.header["BJDREFI"] = 2457000 if mission == "TESS" else 2454833
    ph = fits.PrimaryHDU()
    h = ph.header
    h["OBJECT"] = f"TIC {ident}" if mission == "TESS" else f"KIC {ident}"
    h["TICID" if mission == "TESS" else "KEPLERID"] = ident
    h["SECTOR" if mission == "TESS" else "QUARTER"] = seg
    h["RA_OBJ"], h["DEC_OBJ"], h["DATA_REL"] = 301.5, 44.4, rel
    if drop_key:
        del h[drop_key]
    buf = io.BytesIO()
    fits.HDUList([ph, tab]).writeto(buf)
    return buf.getvalue()


@pytest.fixture
def db():
    return sqlite3.connect(":memory:", check_same_thread=False)


@pytest.fixture
def repo(db):
    return MetadataRepo(db)


@pytest.fixture
def prov(db):
    return SqliteProvenanceStore(db)


@pytest.fixture
def artifacts(db, tmp_path):
    return LocalArtifactStore(tmp_path / "objs", db)


def client_for(handler: Callable[[httpx.Request], httpx.Response], **kw) -> ResilientClient:
    return ResilientClient(
        "test", httpx.Client(transport=httpx.MockTransport(handler)),
        breaker=kw.pop("breaker", CircuitBreaker()), sleep=lambda s: None, **kw,
    )


def tap_json(cols: list[str], rows: list[list]) -> dict:
    return {"metadata": [{"name": c} for c in cols], "data": rows}


def json_resp(body) -> httpx.Response:
    return httpx.Response(200, json=body)


def form(req: httpx.Request) -> dict:
    from urllib.parse import parse_qs
    return {k: v[0] for k, v in parse_qs(req.content.decode()).items()}


__all__ = ["client_for", "form", "json", "json_resp", "make_fits", "tap_json"]
