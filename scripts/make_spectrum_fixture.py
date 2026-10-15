"""Regenerate the demo-mode spectrum sample.

The browser demo cannot run the Python analysis, so it ships one synthetic spectrum together with the
analysis this code produced for it. The demo labels it as precomputed. Run:
    uv run --no-sync python scripts/make_spectrum_fixture.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from akash_science.spectra import REST_LINES, analyze_spectrum

OUT = Path(__file__).resolve().parents[1] / "frontend" / "src" / "api" / "spectrum_sample.json"
Z = 0.35


def main() -> None:
    rng = np.random.default_rng(7)
    w = np.arange(4000.0, 10000.0, 4.0)
    f = 10.0 * (w / 6000.0) ** -0.5 + rng.normal(0, 0.2, len(w))
    for name, amp in (("H-alpha", 1.8), ("H-beta", 0.8), ("[O III] 5007", 1.4), ("[O III] 4959", 0.5),
                      ("[N II] 6584", 0.5)):
        c = REST_LINES[name][0] * (1 + Z)
        s = c * 300.0 / 299792.458 / 2.355
        f = f + 10.0 * amp * np.exp(-0.5 * ((w - c) / s) ** 2)
    wave, flux = [round(float(x), 2) for x in w], [round(float(x), 3) for x in f]
    analysis = analyze_spectrum(wave, flux).to_dict()
    OUT.write_text(json.dumps({"synthetic_truth_z": Z, "wavelength_a": wave, "flux": flux,
                               "analysis": analysis}, separators=(",", ":")))
    print(OUT, analysis["redshift"]["status"], analysis["redshift"]["candidates"][0]["z"])


if __name__ == "__main__":
    main()
