"""Build an anomaly reference population from REAL light curves. RUN WITH INTERNET.

    uv run python scripts/build_anomaly_reference.py star_ids.txt --mission kepler \
        --ref-id kepler-lc-quiet-v1 --out models/anomaly/kepler-lc-quiet-v1 --contact you@example.com

star_ids.txt: one KIC (or TIC) id per line. THE REFERENCE DEFINES "NORMAL", so curate it: pick one
homogeneous population (e.g. Kepler long-cadence, Teff 5000-6500 K, Kp 11-15, quarters 1-17),
exclude known TCE/KOI hosts and known eclipsing binaries, and record the selection in
--criteria. Scores are only meaningful relative to this population. Expect hundreds of stars
at minimum (>=30 fit and >=10 held-out are enforced; ~100 held-out is advisable for stable
percentiles).
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import numpy as np
from akash_core.config import Settings
from akash_data.factory import build_data_layer
from akash_data.lightcurve import NormalizedLightCurve
from akash_ml.anomaly.reference import ReferencePopulation
from akash_science.lightcurve.ephemeris import stitch_lightcurves
from akash_science.lightcurve.variability import UnusableLightCurve, extract_variability


def main() -> None:
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", type=Path)
    ap.add_argument("--mission", choices=["kepler", "tess"], default="kepler")
    ap.add_argument("--ref-id", required=True)
    ap.add_argument("--criteria", default="{}", help="JSON describing how the population was chosen")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--contact", default="")
    ap.add_argument("--data-dir", default="./data")
    ap.add_argument("--aggregate", default="top2", choices=["mean", "top2", "max"])
    a = ap.parse_args()

    dl = build_data_layer(Settings(data_dir=a.data_dir, sqlite_path=f"{a.data_dir}/akash.sqlite3",
                                   contact_email=a.contact))
    svc, ns = (dl.kepler, "KIC") if a.mission == "kepler" else (dl.tess, "TIC")
    vrs, ids, skipped = [], [], []
    for line in a.ids.read_text().split():
        sid = int(line)
        try:
            obj = dl.resolver.resolve(f"{ns} {sid}")
            obs = svc.ingest(obj).observations
            lcs = [NormalizedLightCurve.from_npz_bytes(dl.artifacts.get(dl.prov.get(o.provenance_id).sha256))
                   for o in obs]
            vrs.append(extract_variability(stitch_lightcurves(lcs)))
            ids.append(sid)
        except (UnusableLightCurve, Exception) as e:  # noqa: BLE001  one bad star must not stop a build
            skipped.append((sid, str(e)))
    print(f"{len(vrs)} stars usable, {len(skipped)} skipped")
    ref = ReferencePopulation(a.ref_id, json.loads(a.criteria), seed=0, aggregate=a.aggregate)
    ref.fit(vrs, np.array(ids))
    ref.save(str(a.out))
    print(f"saved reference {a.ref_id} to {a.out} (fingerprint {ref.fingerprint()[:16]})")
    (a.out / "skipped.tsv").write_text("\n".join(f"{s}\t{r}" for s, r in skipped))


if __name__ == "__main__":
    main()
