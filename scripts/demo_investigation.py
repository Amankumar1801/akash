"""Run the deterministic investigation pipeline on labelled SYNTHETIC scenarios and print the
triage outcome, reasons, conflicting evidence and recommended follow-ups for each.

    uv run python scripts/demo_investigation.py [--matrix SCENARIO] [--json out.json]

Light curves are synthetic and the catalogs/Gaia are in-memory fakes, so this demonstrates the
LOGIC (rules, provenance, evidence) and its limits, not astronomical performance. The classifier
is a quick GBM trained on synthetic TCEs."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages/akash_fusion/tests"))
import conftest as C  # noqa: E402  (reuses the test fakes/generators so demo == tests)
from akash_core.schemas import AstronomicalObject, ObjectAlias, ProvenanceRecord  # noqa: E402
from akash_data.storage import LocalArtifactStore  # noqa: E402
from akash_fusion.assembler import InvestigationDeps, investigate  # noqa: E402
from akash_fusion.stellar import StellarService  # noqa: E402
from akash_fusion.store import EvidenceStore  # noqa: E402
from akash_ml.training import TrainConfig, train_system  # noqa: E402
from akash_ml.transit.splits import SplitManifest  # noqa: E402
from akash_ml.transit.synthetic_set import make_synthetic_transit_dataset  # noqa: E402
from akash_provenance import SqliteProvenanceStore  # noqa: E402
from akash_science.injection.models import InjectionSpec  # noqa: E402
from akash_science.lightcurve.pipeline import LightCurvePipeline  # noqa: E402

DENSE = {"source_id": 777, "phot_g_mean_mag": 12.0, "teff_gspphot": 3000.0, "logg_gspphot": 5.5,
         "radius_gspphot": 0.1, "ruwe": 1.0}


def scenarios():
    lc0 = C.make_lc(1)
    t0 = float(lc0.time_bjd[0])
    pl = C.make_lc(1, C.planet(lc0))
    eb = lambda d1, d2: C.make_lc(1, InjectionSpec(4.0, t0 + 1, d1, 0.1),  # noqa: E731
                                  InjectionSpec(4.0, t0 + 3, d2, 0.1))
    return {
        "clean planet": dict(lc=pl),
        "known confirmed planet": dict(lc=pl, catalog=C.FakeCatalog([C.toi(3.2, "CP")])),
        "known false positive": dict(lc=pl, catalog=C.FakeCatalog([C.toi(3.2, "FP")])),
        "star has OTHER catalog entries": dict(lc=pl, catalog=C.FakeCatalog([C.toi(9.9)])),
        "catalog outage": dict(lc=pl, catalog=C.FakeCatalog(fail=True)),
        "nearby source could cause it": dict(lc=pl, gaia=C.FakeGaia(
            neighbors=[C.neighbor(1, 8.0, 16.0)])),
        "compact dwarf (duration impossible)": dict(lc=pl, gaia=C.FakeGaia(star=DENSE)),
        "high-contrast eclipsing binary": dict(lc=eb(0.02, 0.015)),
        "moderate eclipsing binary": dict(lc=eb(0.004, 0.003)),
        "equal-depth binary (degenerate)": dict(lc=eb(0.004, 0.004)),
        "no transit signal": dict(lc=C.make_lc(5)),
    }


def main() -> None:
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", default=None, help="print the evidence matrix for a scenario")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    ds = make_synthetic_transit_dataset(250, seed=1)
    system = train_system(ds, SplitManifest.build(ds.star_ids, "demo"),
                          TrainConfig(run_cnn=False, bootstrap=20), "demo")
    out = {}
    for name, sc in scenarios().items():
        db = sqlite3.connect(":memory:", check_same_thread=False)
        prov = SqliteProvenanceStore(db)
        lcp = prov.add(ProvenanceRecord(
            entity_type="normalized_lightcurve", activity="fetch:synthetic", code_version="demo",
            sha256="ab" * 32, source_uri="https://mast.stsci.edu/synthetic", dataset="TESS-SPOC",
            release="synthetic")).prov_id
        obj = AstronomicalObject(
            ra_deg=301.5, dec_deg=44.4, canonical_name="TIC 1", pm_ra_mas_yr=0.0,
            pm_dec_mas_yr=0.0, aliases=[ObjectAlias(namespace="TIC", identifier="1", source="demo"),
                                        ObjectAlias(namespace="GAIA_DR3", identifier="777",
                                                    source="demo")])
        deps = InvestigationDeps(
            LightCurvePipeline(), prov, LocalArtifactStore(tempfile.mkdtemp(), db), "demo",
            EvidenceStore(db), system, None, sc.get("catalog", C.FakeCatalog()),
            StellarService(sc.get("gaia", C.FakeGaia())))
        r = investigate(obj, sc["lc"], lcp, deps)
        asm = r.assessment
        out[name] = {
            "outcome": r.outcome, "category": asm.triage_category.value if asm else None,
            "reasons": [x.rule for x in asm.triage_reasons] if asm else [],
            "model_probability": round(asm.prediction.planet_like_probability, 2)
            if asm and asm.prediction else None,
            "vetting_concerns": {k: v.value for k, v in asm.vetting.items() if v.value != "pass"}
            if asm else {},
            "n_evidence": len(r.evidence), "n_conflicting": len(asm.conflicting_evidence) if asm else 0,
            "followups": asm.recommended_followup if asm else []}
        if a.matrix == name:
            for row in r.matrix(prov):
                print(f"[{row['agreement']:12s}] {row['channel']:17s} {row['observation'][:90]}"
                      f"\n     source={row['source']['source']} reliability={row['reliability']}"
                      f" version={row['version']}")
    print(f"{'scenario':38s} {'category':22s} model  conflicting  reasons")
    for n, o in out.items():
        print(f"{n:38s} {str(o['category']):22s} {str(o['model_probability']):6s} "
              f"{o['n_conflicting']:^11d}  {','.join(o['reasons'])}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
