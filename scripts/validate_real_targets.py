"""Run AKASH on a few REAL, well-characterised targets and compare the recovered transit period
and depth with published values.

    uv run python scripts/validate_real_targets.py [--targets TIC_ID ...] [--json out.json]

NOT RUN IN THE DEVELOPMENT SANDBOX: it needs outbound HTTPS to MAST, the NASA Exoplanet Archive
and Gaia, which that environment blocks. Everything else in AKASH was validated on synthetic
data or fakes. Run this on a machine with network access before trusting any real-data claim,
and read docs/real-data-validation.md for how to interpret the output.

The reference values below are approximate, rounded from the published literature, and exist
only to catch gross failures (wrong period, wrong order of magnitude depth). They are not a
benchmark. A pass means "same ballpark", not "correct"."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from akash_api.services import build_default_services
from akash_core.config import Settings
from akash_fusion.assembler import investigate

# name, query, mission, approximate published period (d), approximate depth (ppm)
REFERENCE = [
    ("WASP-18 b", "TIC 100100827", "tess", 0.9415, 9000.0),
    ("Pi Mensae c", "TIC 261136679", "tess", 6.2679, 280.0),
    ("TOI-270 c", "TIC 259377017", "tess", 5.6605, 2600.0),
    ("Kepler-10 b", "KIC 11904151", "kepler", 0.8375, 150.0),
]
PERIOD_TOL = 0.02  # fractional
DEPTH_FACTOR = 2.0  # recovered depth within a factor of 2 (depth depends on detrending)


@dataclass
class Row:
    name: str
    query: str
    status: str  # ok | period_mismatch | depth_mismatch | no_transit | error
    period_d: float | None = None
    ref_period_d: float | None = None
    depth_ppm: float | None = None
    ref_depth_ppm: float | None = None
    snr: float | None = None
    category: str | None = None
    note: str = ""


def judge(period: float, depth: float, ref_p: float, ref_d: float) -> str:
    """Accept the true period, or a 2x / 0.5x alias (flagged elsewhere), within PERIOD_TOL."""
    if abs(period - ref_p) / ref_p > PERIOD_TOL:
        return "period_mismatch"
    if not (ref_d / DEPTH_FACTOR <= depth <= ref_d * DEPTH_FACTOR):
        return "depth_mismatch"
    return "ok"


def run_one(services, name, query, mission, ref_p, ref_d) -> Row:  # type: ignore[no-untyped-def]
    row = Row(name, query, "error", ref_period_d=ref_p, ref_depth_ppm=ref_d)
    try:
        with services.context() as ctx:
            obj = services.make_resolver(ctx).resolve(query)
            ctx.repo.save_object(obj)
            bundle = services.make_lightcurve_source(ctx).fetch(obj, mission, [], 3)
            res = investigate(obj, bundle.lc, bundle.prov_id,
                              services.make_investigation_deps(ctx, "deep"), uuid4(), None)
        a = res.assessment
        if a is None or a.transit is None:
            row.status, row.note = "no_transit", f"outcome={res.outcome}"
            return row
        t = a.transit
        row.period_d, row.depth_ppm, row.snr = t.period_d.value, t.depth_ppm, t.snr
        row.category = a.triage_category.value
        row.status = judge(t.period_d.value, t.depth_ppm, ref_p, ref_d)
    except Exception as e:  # noqa: BLE001  (report, keep going to the next target)
        row.note = f"{type(e).__name__}: {str(e)[:160]}"
    return row


def main() -> int:
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", nargs="*", help="only these queries (e.g. 'TIC 100100827')")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    work = tempfile.mkdtemp(prefix="akash-validate-")
    settings = Settings(data_dir=work, sqlite_path=str(Path(work) / "v.sqlite3"))
    services = build_default_services(settings)
    services.ensure_schema()

    rows = [run_one(services, n, q, m, p, d) for n, q, m, p, d in REFERENCE
            if not a.targets or q in a.targets]
    print(f"{'target':<14}{'status':<17}{'period d':>10}{'ref':>9}{'depth ppm':>11}{'ref':>8}"
          f"{'snr':>7}  category")
    for r in rows:
        f = lambda v, w, p=2: f"{v:>{w}.{p}f}" if v is not None else f"{'-':>{w}}"  # noqa: E731
        print(f"{r.name:<14}{r.status:<17}{f(r.period_d, 10, 4)}{f(r.ref_period_d, 9, 4)}"
              f"{f(r.depth_ppm, 11, 0)}{f(r.ref_depth_ppm, 8, 0)}{f(r.snr, 7, 1)}  "
              f"{r.category or r.note}")
    if a.json:
        Path(a.json).write_text(json.dumps([asdict(r) for r in rows], indent=2))
    ok = sum(r.status == "ok" for r in rows)
    print(f"\n{ok}/{len(rows)} within tolerance. Same-ballpark check only; "
          "AKASH assists investigation; it does not independently establish discoveries.")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
