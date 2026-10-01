"""Record REAL archive responses so tests can replay them offline.

Run on a machine with internet access:
    uv run python scripts/record_fixtures.py "KIC 8462852" --out packages/akash_data/tests/fixtures/boyajian
Then point a test at ReplayTransport(<that dir>). Commit the fixtures. Re-run occasionally
to catch upstream schema drift (compare the diff).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx
from akash_core.config import Settings
from akash_data.base import ObsFilter
from akash_data.factory import build_data_layer
from akash_data.testing import RecordingTransport


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--max-obs", type=int, default=1, help="light curves to download (keep small)")
    ap.add_argument("--mission", choices=["tess", "kepler"], default="kepler")
    a = ap.parse_args()

    settings = Settings(data_dir=str(a.out / "_work"), sqlite_path=str(a.out / "_work" / "m.sqlite3"))
    dl = build_data_layer(settings, transport=RecordingTransport(a.out, httpx.HTTPTransport()))
    obj = dl.resolver.resolve(a.query)
    print("resolved:", obj.canonical_name, {x.namespace: x.identifier for x in obj.aliases if x.namespace != "SIMBAD"})
    dl.exoplanet_archive.lookup(obj)
    dl.gaia.lookup(obj)
    svc = dl.kepler if a.mission == "kepler" else dl.tess
    res = svc.ingest(obj, ObsFilter(max_observations=a.max_obs))
    print("ingested:", len(res.observations), "quarantined:", res.quarantined, "errors:", res.errors)


if __name__ == "__main__":
    main()
