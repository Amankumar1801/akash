"""Wire real components together from Settings. Tests construct pieces directly instead."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import httpx
from akash_core import __version__
from akash_core.config import Settings
from akash_provenance import SqliteProvenanceStore

from .http import CircuitBreaker, ResilientClient, TokenBucket
from .identity.resolver import Resolver
from .ingest import ObservationService
from .providers.exoplanet_archive import ExoplanetArchiveProvider
from .providers.gaia import GaiaProvider
from .providers.mast import KEPLER_LC, TESS_SPOC, MastLightCurveProvider
from .providers.simbad import SIMBAD_TAP, SimbadClient
from .providers.tap import TapClient
from .storage import LocalArtifactStore, MetadataRepo


@dataclass
class DataLayer:
    repo: MetadataRepo
    artifacts: LocalArtifactStore
    prov: SqliteProvenanceStore
    resolver: Resolver
    gaia: GaiaProvider
    exoplanet_archive: ExoplanetArchiveProvider
    tess: ObservationService
    kepler: ObservationService


def build_data_layer(settings: Settings, transport: httpx.BaseTransport | None = None) -> DataLayer:
    Path(settings.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.sqlite_path, check_same_thread=False)
    repo, prov = MetadataRepo(conn), SqliteProvenanceStore(conn)
    artifacts = LocalArtifactStore(Path(settings.data_dir) / "objects", conn)
    ua = f"AKASH/{__version__} (+{settings.contact_email or 'no-contact-set'})"

    def client(name: str, rate: float) -> ResilientClient:
        return ResilientClient(
            name,
            httpx.Client(headers={"User-Agent": ua}, timeout=60.0, transport=transport,
                         follow_redirects=True),
            bucket=TokenBucket(rate), breaker=CircuitBreaker(),
        )

    simbad_http, gaia_http = client("simbad", 5.0), client("gaia", 2.0)
    ipac_http, mast_http = client("exoplanet_archive", 2.0), client("mast", 5.0)
    gaia = GaiaProvider(gaia_http)
    resolver = Resolver(repo, SimbadClient(TapClient(simbad_http, SIMBAD_TAP)), gaia)
    cv = settings.pipeline_version
    return DataLayer(
        repo, artifacts, prov, resolver, gaia, ExoplanetArchiveProvider(ipac_http),
        ObservationService(MastLightCurveProvider(mast_http, TESS_SPOC), artifacts, repo, prov, cv),
        ObservationService(MastLightCurveProvider(mast_http, KEPLER_LC), artifacts, repo, prov, cv),
    )
