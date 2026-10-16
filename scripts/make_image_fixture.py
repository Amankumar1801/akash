"""Regenerate the demo-mode image sample: a synthetic galaxy with its analysis from the Python code.

    uv run --no-sync python scripts/make_image_fixture.py
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np
from akash_science.imaging import analyze_image, downsample_for_preview

OUT = Path(__file__).resolve().parents[1] / "frontend" / "src" / "api" / "image_sample.json"


def main() -> None:
    rng = np.random.default_rng(11)
    size = 96
    y, x = np.indices((size, size)).astype(float)
    x, y = x - size / 2, y - size / 2
    th = np.radians(40.0)
    xr, yr = np.cos(th) * x + np.sin(th) * y, -np.sin(th) * x + np.cos(th) * y
    r = np.sqrt(xr**2 + (yr / 0.65) ** 2)
    n = 1.5
    bn = 2 * n - 1 / 3 + 0.009876 / n
    img = 90.0 * np.exp(-bn * ((r / 7.0) ** (1 / n) - 1))
    img += 25.0 * np.exp(-0.5 * (((x - 22) ** 2 + (y + 12) ** 2) / 3.0**2))      # a small companion
    img += rng.normal(0, 1.0, img.shape)
    pix = img.astype("<f4")
    analysis = analyze_image(pix).to_dict()
    analysis.update(preview=downsample_for_preview(pix), label=None, input_kind="pixels")
    OUT.write_text(json.dumps({"width": size, "height": size,
                               "pixels_b64": base64.b64encode(pix.tobytes()).decode("ascii"),
                               "analysis": analysis}, separators=(",", ":")))
    s = analysis["source"]
    print(OUT, analysis["status"], round(s["concentration"], 2), round(s["asymmetry"], 2))


if __name__ == "__main__":
    main()
