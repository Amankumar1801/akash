"""Build the real Kepler training set from the DR25 TCE table. RUN ON A MACHINE WITH INTERNET.

    uv run python scripts/build_kepler_training_set.py tce_table.csv --out data/kepler_dr25.npz \
        --contact you@example.com [--max-stars 500]

For every star: resolve KIC -> ingest all Kepler long-cadence quarters (Phase 1 data layer, with
caching + provenance) -> stitch -> fold at the catalog ephemeris -> views + features.
The full table is ~16k stars / ~34k TCEs and needs hundreds of GB of downloads and many hours;
start with --max-stars to validate the whole path first. Re-running resumes from the cache.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from akash_core.config import Settings
from akash_data.factory import build_data_layer
from akash_data.lightcurve import NormalizedLightCurve
from akash_ml.transit.build import build_dataset, lightcurve_getter, load_kepler_dr25_csv


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tce_csv", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--contact", default="", help="email for the archive User-Agent")
    ap.add_argument("--max-stars", type=int, default=None)
    ap.add_argument("--data-dir", default="./data")
    a = ap.parse_args()

    recs = load_kepler_dr25_csv(a.tce_csv)
    if a.max_stars:
        keep = sorted({r.star_id for r in recs})[: a.max_stars]
        recs = [r for r in recs if r.star_id in set(keep)]
    print(f"{len(recs)} labelled TCEs over {len({r.star_id for r in recs})} stars "
          f"({sum(r.label for r in recs)} positive)")

    dl = build_data_layer(Settings(data_dir=a.data_dir, sqlite_path=f"{a.data_dir}/akash.sqlite3",
                                   contact_email=a.contact))

    def load_normalized(obs) -> NormalizedLightCurve:
        sha = dl.prov.get(obs.provenance_id).sha256  # normalized-npz content hash
        return NormalizedLightCurve.from_npz_bytes(dl.artifacts.get(sha))

    get = lightcurve_getter(lambda k: dl.resolver.resolve(f"KIC {k}"),
                            lambda o: dl.kepler.ingest(o).observations, load_normalized)
    skipped: list[tuple[str, str]] = []
    ds = build_dataset(recs, get, skipped)
    h = ds.save(a.out)
    print(f"saved {len(ds)} TCEs to {a.out} (content hash {h[:16]}); skipped {len(skipped)}")
    (a.out.with_suffix(".skipped.tsv")).write_text("\n".join(f"{t}\t{r}" for t, r in skipped))


if __name__ == "__main__":
    main()
