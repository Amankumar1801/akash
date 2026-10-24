"""Find out why an investigation has no stellar parameters (radius, density, RUWE, contamination).

    uv run --no-sync python scripts/diagnose_gaia.py "TIC 261136679"
    uv run --no-sync python scripts/diagnose_gaia.py "TIC 261136679" --fresh

It checks, in order, the three places that can break the Gaia step and says which one did:
  1. can this machine reach the Gaia archive at all (and how fast)?
  2. does the star have a Gaia DR3 id in AKASH's identity record?
  3. does the Gaia record carry stellar parameters (some very bright stars have none)?

Without --fresh it uses the same database as the API (so it sees a stale cached identity);
with --fresh it uses an empty temporary one. Needs internet access."""

from __future__ import annotations

import argparse
import tempfile
import time
import warnings
from pathlib import Path

from akash_api.services import build_default_services
from akash_core.config import Settings
from akash_data.factory import build_data_layer
from akash_fusion.stellar import StellarService


def main() -> int:
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="e.g. 'TIC 261136679'")
    ap.add_argument("--fresh", action="store_true", help="use an empty temporary database")
    a = ap.parse_args()

    settings = Settings()
    if a.fresh:
        work = tempfile.mkdtemp(prefix="akash-gaia-")
        settings = Settings(data_dir=work, sqlite_path=str(Path(work) / "d.sqlite3"))
    print(f"database: {settings.sqlite_path}{'  (fresh, empty)' if a.fresh else ''}")
    services = build_default_services(settings)
    services.ensure_schema()

    with services.context() as ctx:
        layer = build_data_layer(settings, conn=ctx.conn)

        print("\n1. Reaching the Gaia archive ...")
        t0 = time.time()
        try:
            layer.gaia.tap.query("SELECT TOP 1 source_id FROM gaiadr3.gaia_source")
            print(f"   OK in {time.time() - t0:.1f} s")
        except Exception as e:  # noqa: BLE001  (this is a diagnostic: show whatever went wrong)
            print(f"   FAILED after {time.time() - t0:.1f} s: {type(e).__name__}: {e}")
            print("\nVERDICT: the Gaia archive is not reachable from this machine right now.")
            print("  Try again in a few minutes (ESA's archive has maintenance windows), check a")
            print("  VPN/firewall/proxy, and make sure https://gea.esac.esa.int opens in a browser.")
            return 1

        print(f"\n2. Resolving {a.query!r} ...")
        obj = services.make_resolver(ctx).resolve(a.query)
        gid = obj.alias("GAIA_DR3")
        print(f"   {obj.canonical_name}  RA {obj.ra_deg:.4f}  Dec {obj.dec_deg:.4f}")
        print(f"   anchor: {obj.anchor_namespace}   Gaia DR3 id: {gid or 'NONE'}")
        if gid is None:
            print("\nVERDICT: the star has no Gaia DR3 id in its identity record, so the Gaia step")
            print("  is skipped. The cross-match found zero or several Gaia sources near it.")
            print("  Try with --fresh to rule out a stale cached identity.")
            return 1

        print("\n3. Stellar parameters from Gaia ...")
        try:
            prof = StellarService(layer.gaia).profile(obj)
        except Exception as e:  # noqa: BLE001  (diagnostic: show whatever went wrong)
            print(f"   FAILED: {type(e).__name__}: {e}")
            print("\nVERDICT: Gaia is reachable but refused the stellar-parameter query.")
            print("  The message above is Gaia's own reason. Send it to the developer.")
            return 1
        if layer.gaia.dropped:
            print(f"   note: Gaia rejected these columns, so they were left out: "
                  f"{', '.join(layer.gaia.dropped)}")
        if prof is None:
            print("   Gaia returned no record for that id.")
            return 1
        print(f"   G mag {prof.g_mag}  Teff {prof.teff}  logg {prof.logg}  "
              f"radius {prof.radius_rsun} Rsun  RUWE {prof.ruwe}")
        print(f"   neighbours within {StellarService(layer.gaia).search_radius:.0f} arcsec: "
              f"{len(prof.neighbors)}")
        if layer.gaia.dropped:
            print(f"\nVERDICT: part of the Gaia request failed ({', '.join(layer.gaia.dropped)}).")
            print("  That is a bug in AKASH's Gaia query, not a data gap. Send this output to the developer.")
            return 1
        missing = [n for n, v in (("radius", prof.radius_rsun), ("logg", prof.logg),
                                  ("Teff", prof.teff)) if v is None]
        if missing:
            print(f"\nVERDICT: Gaia knows this star but has no {', '.join(missing)} for it")
            print("  (the GSP-Phot pipeline leaves these empty for some very bright stars). The")
            print("  two stellar-based checks will stay inconclusive; this is a data gap, not a bug.")
            return 2
    print("\nVERDICT: the Gaia step works. If an investigation still lacks stellar parameters,")
    print("  start a new one (old results are not recomputed) and read its log.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
