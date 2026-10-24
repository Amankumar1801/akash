"""Render AKASH's illustrative space scenes to WebP (frontend/public/assets/space).

    uv run python scripts/make_space_assets.py [--only hero ...] [--out DIR]

These are ILLUSTRATIONS rendered from physical-looking models (limb darkening, atmospheric rim
light, log-spiral arms, bloom), not photographs and not observations. They never depict a real
target. Every file is deterministic (fixed seeds), so the library can be rebuilt byte for byte.

To use a genuine NASA/ESA photograph instead, drop a file with the same name into the output
folder (see frontend/public/assets/space/README.md). The interface only references these names.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

F = np.float32
BG = np.array([5, 8, 16], dtype=F) / 255.0  # --night


# ---------------------------------------------------------------- primitives
def fbm(h: int, w: int, rng: np.random.Generator, octaves: int = 6, base: int = 3,
        gain: float = 0.55, aspect: float = 1.0) -> np.ndarray:
    """Fractal value noise in [0, 1] via bicubic-upsampled random grids."""
    out = np.zeros((h, w), F)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        n = base * 2**o
        gw, gh = n + 2, max(2, int(n * aspect * h / w) + 2)
        g = rng.standard_normal((gh, gw)).astype(F)
        out += amp * np.asarray(Image.fromarray(g, "F").resize((w, h), Image.BICUBIC), F)
        tot += amp
        amp *= gain
    out /= tot
    out -= out.min()
    return out / max(float(out.max()), 1e-6)


def grid(h: int, w: int) -> tuple[np.ndarray, np.ndarray]:
    yy, xx = np.mgrid[0:h, 0:w].astype(F)
    return xx, yy


def blur(a: np.ndarray, s: float) -> np.ndarray:
    return ndi.gaussian_filter(a, (s, s, 0) if a.ndim == 3 else s).astype(F)


def smooth(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def col(*rgb: float) -> np.ndarray:
    return np.array(rgb, F)


def starfield(h: int, w: int, rng: np.random.Generator, density: float = 1.0,
              gain: float = 1.0, mask: np.ndarray | None = None) -> np.ndarray:
    n = int(h * w * 0.0011 * density)
    x, y = rng.uniform(0, w, n), rng.uniform(0, h, n)
    if mask is not None:  # keep stars where the mask is bright, so stars thicken inside a galaxy band
        keep = rng.uniform(0, 1, n) < mask[np.clip(y.astype(int), 0, h - 1), np.clip(x.astype(int), 0, w - 1)]
        x, y = x[keep], y[keep]
        n = len(x)
    inten = np.clip(0.04 + 0.22 * rng.pareto(1.9, n), 0, 4.0).astype(F) * gain
    t = rng.uniform(0, 1, n)[:, None]
    tint = (1 - t) * col(0.72, 0.84, 1.0) + t * col(1.0, 0.84, 0.64)
    layer = np.zeros((h, w, 3), F)
    xi, yi = np.clip(x.astype(int), 0, w - 1), np.clip(y.astype(int), 0, h - 1)
    for c in range(3):
        np.add.at(layer[..., c], (yi, xi), inten * tint[:, c])
    layer = blur(layer, 0.75) * 3.2
    order = np.argsort(-inten)[: max(6, n // 260)]  # the brightest few get bloom and faint spikes
    bloom = np.zeros((h, w, 3), F)
    spikes = np.zeros((h, w, 3), F)
    ax = np.arange(w, dtype=F)
    ay = np.arange(h, dtype=F)
    for i in order:
        if inten[i] < 0.5:
            continue
        L = 14 + 18 * min(inten[i], 2.5)
        row = np.exp(-np.abs(ax - x[i]) / L * 2.2)
        colm = np.exp(-np.abs(ay - y[i]) / L * 2.2)
        yy0 = int(np.clip(yi[i], 0, h - 1))
        xx0 = int(np.clip(xi[i], 0, w - 1))
        spikes[yy0, :, :] += (0.16 * inten[i] * row)[:, None] * tint[i]
        spikes[:, xx0, :] += (0.16 * inten[i] * colm)[:, None] * tint[i]
        bloom[yy0, xx0] += inten[i] * tint[i]
    return layer + spikes + blur(bloom, 3.2) * 18.0 + blur(bloom, 9) * 28.0


def nebula(h: int, w: int, rng: np.random.Generator, cols: list[tuple[float, float, float]],
           strength: float = 0.25, base: int = 3) -> np.ndarray:
    out = np.zeros((h, w, 3), F)
    for c in cols:
        m = fbm(h, w, rng, octaves=6, base=base, gain=0.58, aspect=1.2)
        m = np.maximum(m - 0.46, 0) ** 1.7
        out += m[..., None] * col(*c) * strength * 4.0
    return out


def vignette_fade(h: int, w: int, left: float = 0.0, r: float = 0.0, t: float = 0.0, b: float = 0.0) -> np.ndarray:
    xx, yy = grid(h, w)
    m = np.ones((h, w), F)
    if left:
        m *= smooth(0, left * w, xx)
    if r:
        m *= smooth(0, r * w, (w - 1) - xx)
    if t:
        m *= smooth(0, t * h, yy)
    if b:
        m *= smooth(0, b * h, (h - 1) - yy)
    return m[..., None]


def sun_flare(h: int, w: int, cx: float, cy: float, core: float, color: np.ndarray,
              streak: float = 1.0, vstreak: float = 0.25) -> np.ndarray:
    xx, yy = grid(h, w)
    dx, dy = xx - cx, yy - cy
    d = np.hypot(dx, dy) + 1e-3
    glow = np.exp(-(d / core) ** 2) * 6.0 + 1.0 / (1.0 + (d / (core * 5.0)) ** 2) ** 1.35 * 0.55
    glow += 1.0 / (1.0 + (d / (core * 22.0)) ** 2) * 0.026
    hs = np.exp(-np.abs(dy) / (core * 0.30)) * np.exp(-np.abs(dx) / (core * 48.0)) * 0.60 * streak
    vs = np.exp(-np.abs(dx) / (core * 0.30)) * np.exp(-np.abs(dy) / (core * 16.0)) * 0.30 * vstreak
    white = col(1.0, 0.97, 0.9)
    k = np.clip(np.exp(-(d / (core * 1.4)) ** 2), 0, 1)[..., None]
    base = color * (glow + hs + vs)[..., None]
    return base * (1 - k) + white * (glow + hs + vs)[..., None] * k


def planet(h: int, w: int, cx: float, cy: float, R: float, light: tuple[float, float, float],
           surface: np.ndarray, atmo: np.ndarray, atmo_gain: float, rng: np.random.Generator,
           bands: float = 1.0, glow_gain: float = 1.0, night: float = 0.02,
           rim_px: float | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (colour, coverage, outer glow) of a limb-darkened, atmosphere-rimmed sphere."""
    xx, yy = grid(h, w)
    dx, dy = (xx - cx) / R, (yy - cy) / R
    rr = np.sqrt(dx * dx + dy * dy)
    nz = np.sqrt(np.clip(1 - rr * rr, 0, 1))
    L = np.array(light, F)
    L /= np.linalg.norm(L)
    ndl = np.clip(dx * L[0] + dy * L[1] + nz * L[2], 0, 1)
    lat = fbm(h, w, rng, octaves=5, base=2, gain=0.6)
    band = 0.5 + 0.5 * np.sin(dy * 9.0 + 3.2 * (lat - 0.5) * 4.0)
    tex = 0.62 + bands * (0.28 * band + 0.20 * (lat - 0.5))
    soft = ndl ** 0.85
    surf = surface[None, None, :] * tex[..., None] * (soft[..., None] + night)
    limb = (1 - nz) ** 3.2 if rim_px is None else np.exp(-np.clip(1 - rr, 0, None) * R / rim_px)
    rim = limb * (0.10 + 1.15 * ndl ** 0.6)
    colr = surf + atmo * (rim * atmo_gain)[..., None]
    cover = np.clip((1 - rr) * R / 1.1 + 0.5, 0, 1)
    out = np.clip(rr - 1, 0, None)
    sunward = np.clip(0.30 + 0.70 * ((dx * L[0] + dy * L[1]) / np.maximum(rr, 1e-3)) * 0.5 + 0.35, 0, 1.3)
    glow = np.exp(-out * 9.0) * 0.55 + np.exp(-out * 2.6) * 0.10
    glow = glow * sunward * (rr >= 1) * glow_gain
    return colr.astype(F), cover[..., None].astype(F), (atmo * glow[..., None]).astype(F)


def tonemap(img: np.ndarray, exposure: float = 1.0, rng: np.random.Generator | None = None,
            lift: float = 0.0) -> np.ndarray:
    x = 1.0 - np.exp(-np.maximum(img, 0) * exposure)
    x = np.clip(x + BG * lift * (1 - x), 0, 1)
    if rng is not None:  # dither, to hide banding in the dark gradients
        x = x + (rng.random(x.shape, dtype=F) - 0.5) / 255.0
    return np.clip(x * 255.0 + 0.5, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- galaxy / disk
def galaxy(h: int, w: int, rng: np.random.Generator, cx: float, cy: float, R: float,
           incl: float = 0.6, rot: float = 0.0, arms: int = 2, pitch: float = 0.30,
           warm: tuple[float, float, float] = (1.0, 0.80, 0.52),
           cool: tuple[float, float, float] = (0.50, 0.66, 1.0),
           pink: tuple[float, float, float] = (1.0, 0.36, 0.55),
           bulge: float = 1.6, dust: float = 0.7, stars: int = 9000, tight: float = 3.0
           ) -> np.ndarray:
    xx, yy = grid(h, w)
    dx, dy = xx - cx, yy - cy
    c, s = math.cos(rot), math.sin(rot)
    u = dx * c + dy * s
    v = (-dx * s + dy * c) / incl
    r = np.hypot(u, v) / R + 1e-4
    th = np.arctan2(v, u)
    phase = arms * (th - np.log(r) / pitch)
    arm = (0.5 + 0.5 * np.cos(phase)) ** tight
    clump = fbm(h, w, rng, octaves=6, base=4, gain=0.62)
    disk = np.exp(-r * 2.3)
    dens = disk * (0.16 + arm * (0.70 + 1.25 * clump))
    core = np.exp(-(r / 0.11) ** 0.85) * bulge
    d3 = (core + dens)[..., None]
    tint = col(*warm) * np.exp(-r * 2.6)[..., None] + col(*cool) * (1 - np.exp(-r * 2.6))[..., None]
    hii = (arm * smooth(0.45, 0.85, clump) * smooth(0.12, 0.4, r) * np.exp(-r * 1.4))[..., None] * col(*pink)
    img = d3 * tint * 1.25 + hii * 1.5
    lane = (0.5 + 0.5 * np.cos(phase - 0.55)) ** 4 * fbm(h, w, rng, octaves=6, base=6, gain=0.65) * np.exp(-r * 1.2)
    img *= (1 - dust * np.clip(lane * 2.2, 0, 0.85))[..., None]
    halo = np.exp(-r * 1.1) * 0.05
    img += halo[..., None] * col(*warm) * 0.5
    p = (dens + core * 0.5).ravel().astype(np.float64)
    p /= p.sum()
    idx = rng.choice(p.size, size=stars, p=p)
    sy, sx = np.divmod(idx, w)
    lay = np.zeros((h, w, 3), F)
    br = np.clip(0.2 + 0.5 * rng.pareto(2.0, stars), 0, 3).astype(F)
    for ch in range(3):
        np.add.at(lay[..., ch], (sy, sx), br * tint[sy, sx, ch])
    img += blur(lay, 0.9) * 3.0
    return img


# ---------------------------------------------------------------- scenes
def scene_background(rng: np.random.Generator) -> np.ndarray:
    h, w = 1500, 2400
    img = np.zeros((h, w, 3), F)
    img += nebula(h, w, rng, [(0.10, 0.22, 0.55), (0.35, 0.12, 0.45), (0.05, 0.30, 0.38)], 0.20, base=2)
    for _ in range(26):  # a few very distant, tiny galaxies
        gx, gy = rng.uniform(0, w), rng.uniform(0, h)
        s = rng.uniform(5, 15)
        gal = galaxy(64, 96, rng, 48, 32, s, incl=rng.uniform(.25, .9), rot=rng.uniform(0, 3), stars=0,
                     dust=0.0)
        x0, y0 = int(np.clip(gx - 48, 0, w - 96)), int(np.clip(gy - 32, 0, h - 64))
        img[y0:y0 + 64, x0:x0 + 96] += gal * 0.9
    img += starfield(h, w, rng, 1.0, 1.0)
    return tonemap(img, 1.15, rng, lift=1.0)


def scene_hero(rng: np.random.Generator) -> np.ndarray:
    h, w = 1200, 2000
    img = np.zeros((h, w, 3), F)
    img += nebula(h, w, rng, [(0.10, 0.20, 0.55), (0.45, 0.20, 0.30)], 0.14)
    img += starfield(h, w, rng, 0.85)
    sx, sy = 0.80 * w, 0.655 * h
    warm = col(1.0, 0.66, 0.30)
    xx0, yy0 = grid(h, w)
    d0 = np.hypot(xx0 - sx, yy0 - sy)  # warm light from a star just out of frame: glow, but no disc
    img += (1.0 / (1.0 + (d0 / (0.075 * w)) ** 2) ** 1.3 * 0.55 + 1.0 / (1.0 + (d0 / (0.32 * w)) ** 2) * 0.10)[..., None] * warm
    cx, cy, R = 0.58 * w, 3.35 * h, 2.65 * h  # a very large planet: only its limb crosses the frame
    colr, cover, glow = planet(h, w, cx, cy, R, (0.55, -0.80, 0.25), col(0.05, 0.08, 0.15),
                               col(1.0, 0.62, 0.30), 2.6, rng, bands=0.7, glow_gain=1.2, rim_px=34)
    xx, yy = grid(h, w)
    near = np.exp(-((xx - sx) / (0.20 * w)) ** 2)[..., None]  # the limb catches the star's light
    img = img * (1 - cover) + colr * cover + glow * (0.5 + 1.8 * near)
    cool = np.exp(-np.clip(np.hypot((xx - cx) / R, (yy - cy) / R) - 1, 0, None) * 5.0)[..., None] * col(0.10, 0.25, 0.6)
    img += cool * 0.22 * (1 - near) * (np.hypot((xx - cx) / R, (yy - cy) / R) >= 1)[..., None]
    img *= vignette_fade(h, w, left=0.30, t=0.20)
    return tonemap(img, 1.0, rng)


def scene_candidates(rng: np.random.Generator) -> np.ndarray:
    h, w = 1000, 1800
    img = np.zeros((h, w, 3), F)
    img += nebula(h, w, rng, [(0.45, 0.14, 0.40), (0.12, 0.18, 0.5)], 0.13)
    img += starfield(h, w, rng, 0.8)
    disk = galaxy(h, w, rng, 0.70 * w, 0.40 * h, 0.58 * h, incl=0.62, rot=-0.42, arms=3, pitch=0.34,
                  warm=(1.0, 0.72, 0.38), cool=(1.0, 0.48, 0.28), pink=(0.88, 0.30, 0.58),
                  bulge=3.2, dust=0.85, stars=11000, tight=2.4)
    img += disk * 1.25
    xx, yy = grid(h, w)
    d = np.hypot(xx - 0.70 * w, (yy - 0.40 * h) / 0.62)
    img += (np.exp(-(d / 38) ** 2) * 2.4 + np.exp(-d / 150) * 0.22)[..., None] * col(1.0, 0.82, 0.55)
    img *= vignette_fade(h, w, left=0.38, b=0.30, t=0.04, r=0.02)
    return tonemap(img, 1.0, rng)


def scene_sky(rng: np.random.Generator) -> np.ndarray:
    h, w = 900, 1800
    xx, yy = grid(h, w)
    t = xx / w
    cy = h * (0.60 - 0.34 * np.sin(np.pi * t) ** 1.3 + 0.10 * (t - 0.5))  # an arch across the sky
    d = (yy - cy) / (0.15 * h)
    band = np.exp(-d * d)
    tex = fbm(h, w, rng, octaves=7, base=5, gain=0.62, aspect=2.0)
    lane = fbm(h, w, rng, octaves=7, base=7, gain=0.66, aspect=2.0)
    dens = band * (0.10 + 1.55 * tex ** 2.1)
    dens *= 1 - 0.80 * smooth(0.50, 0.78, lane) * np.exp(-(d * 0.9) ** 2)
    corew = np.exp(-(((xx - 0.50 * w) / (0.14 * w)) ** 2 + ((yy - cy) / (0.10 * h)) ** 2))
    img = dens[..., None] * (col(0.50, 0.58, 0.92) * (1 - corew[..., None]) + col(1.0, 0.76, 0.50) * corew[..., None]) * 0.80
    img += (corew * 0.8)[..., None] * col(1.0, 0.8, 0.55)
    img += starfield(h, w, rng, 0.8) + starfield(h, w, rng, 4.2, 0.62, mask=np.clip(band * 1.3, 0, 1))
    air = np.exp(-((h * 0.82 - yy) / (0.10 * h)) ** 2) * smooth(0.55 * h, 0.9 * h, yy)
    img += air[..., None] * col(0.05, 0.28, 0.30) * 0.30
    ridge = fbm(1, w, rng, octaves=7, base=3, gain=0.6)[0]
    ridge_y = h * (0.865 + 0.07 * (ridge - 0.5) * 2.2)
    ridge2 = fbm(1, w, rng, octaves=7, base=6, gain=0.62)[0]
    ridge_y = ridge_y + 0.012 * h * (ridge2 - 0.5)
    land = smooth(-1.2, 1.2, yy - ridge_y[None, :])
    edge = np.exp(-((yy - ridge_y[None, :]) / 3.0) ** 2) * 0.14
    img = img * (1 - land[..., None]) + col(0.015, 0.02, 0.04) * land[..., None] + edge[..., None] * col(0.35, 0.5, 0.9) * 0.4
    img *= vignette_fade(h, w, left=0.12, r=0.10, t=0.10, b=0.02)
    return tonemap(img, 1.05, rng)


def scene_models(rng: np.random.Generator) -> np.ndarray:
    h, w = 900, 1800
    img = np.zeros((h, w, 3), F)
    img += nebula(h, w, rng, [(0.08, 0.20, 0.55)], 0.11)
    img += starfield(h, w, rng, 0.8)
    colr, cover, glow = planet(h, w, 0.80 * w, 0.62 * h, 0.78 * h, (-0.85, -0.45, 0.10),
                               col(0.07, 0.17, 0.34), col(0.32, 0.62, 1.0), 2.4, rng, bands=1.3, glow_gain=1.4, rim_px=70)
    img = img * (1 - cover) + colr * cover + glow
    xx, yy = grid(h, w)
    img += sun_flare(h, w, 0.40 * w, 0.18 * h, 10, col(0.8, 0.9, 1.0), streak=0.5, vstreak=0.3) * 0.5
    img *= vignette_fade(h, w, left=0.36, t=0.10, b=0.18, r=0.0)
    return tonemap(img, 1.0, rng)


def scene_lab(rng: np.random.Generator) -> np.ndarray:
    h, w = 1000, 1600
    xx, yy = grid(h, w)
    img = np.zeros((h, w, 3), F)
    img += nebula(h, w, rng, [(0.45, 0.16, 0.08)], 0.10)
    img += starfield(h, w, rng, 0.8)
    cx, cy, rot = 0.70 * w, 0.46 * h, -0.36
    c, s = math.cos(rot), math.sin(rot)
    u = (xx - cx) * c + (yy - cy) * s
    v = -(xx - cx) * s + (yy - cy) * c
    ang = np.arctan2(v, u)
    orange, hot = col(1.0, 0.50, 0.12), col(1.0, 0.86, 0.60)
    for a_r, tilt, thick, bright in [(0.20, 0.30, 3.0, 0.9), (0.31, 0.32, 5.0, 1.0), (0.42, 0.34, 2.2, 0.7),
                                     (0.54, 0.36, 7.0, 1.0), (0.69, 0.38, 3.0, 0.6)]:
        a, b = a_r * h * 1.6, a_r * h * 1.6 * tilt
        f = np.hypot(u / a, v / b)
        dist = np.abs(f - 1) * min(a, b) * 1.35
        wob = 0.55 + 0.45 * np.sin(ang * 3 + a_r * 40) * np.sin(ang * 2 - a_r * 13)
        wob *= 0.7 + 0.5 * fbm(h, w, rng, octaves=4, base=3)
        ring = np.exp(-(dist / thick) ** 2) * wob * bright
        halo = np.exp(-dist / (thick * 7)) * 0.10 * bright
        img += ring[..., None] * (orange * 0.8 + hot * 0.5) * 2.2 + halo[..., None] * orange
        n = 1400
        th = rng.uniform(0, 2 * np.pi, n)
        rr = 1 + rng.normal(0, 0.012 + thick * 0.0022, n)
        px = cx + (a * rr * np.cos(th)) * c - (b * rr * np.sin(th)) * s
        py = cy + (a * rr * np.cos(th)) * s + (b * rr * np.sin(th)) * c
        ok = (px >= 0) & (px < w) & (py >= 0) & (py < h)
        lay = np.zeros((h, w, 3), F)
        for ch in range(3):
            np.add.at(lay[..., ch], (py[ok].astype(int), px[ok].astype(int)), rng.uniform(0.3, 1.4, ok.sum()) * hot[ch])
        img += blur(lay, 1.0) * 3.0
    d0 = np.hypot(xx - cx, (yy - cy) / 0.9)
    img += (np.exp(-(d0 / 28) ** 2) * 2.4 + np.exp(-d0 / 120) * 0.30)[..., None] * col(1.0, 0.62, 0.22)
    img *= vignette_fade(h, w, left=0.40, b=0.22, t=0.10, r=0.02)
    return tonemap(img, 0.95, rng)


def scene_galaxy_image(rng: np.random.Generator) -> np.ndarray:
    h, w = 800, 1200
    img = np.zeros((h, w, 3), F)
    img += nebula(h, w, rng, [(0.10, 0.16, 0.45)], 0.08)
    img += starfield(h, w, rng, 1.0)
    img += galaxy(h, w, rng, 0.52 * w, 0.50 * h, 0.40 * h, incl=0.78, rot=-0.55, arms=2, pitch=0.32,
                  warm=(1.0, 0.82, 0.55), cool=(0.52, 0.68, 1.0), pink=(1.0, 0.34, 0.56),
                  bulge=2.0, dust=0.9, stars=16000, tight=2.8) * 1.15
    img *= vignette_fade(h, w, left=0.03, r=0.03, t=0.03, b=0.03)
    return tonemap(img, 1.0, rng)


# ---- case thumbnails (520 x 390): one rendering routine, eight compositions
def thumb(kind: str, rng: np.random.Generator) -> np.ndarray:
    h, w = 390, 520
    img = np.zeros((h, w, 3), F)
    img += nebula(h, w, rng, [(0.10, 0.18, 0.5)], 0.10, base=2)
    img += starfield(h, w, rng, 1.3, 0.9)
    xx, yy = grid(h, w)
    if kind == "clean-transit":      # a blue planet with a thin luminous atmosphere
        img += sun_flare(h, w, 0.30 * w, 0.16 * h, 7, col(1.0, 0.82, 0.55), 0.5, 0.3) * 0.5
        colr, cv, gl = planet(h, w, 0.50 * w, 0.58 * h, 0.30 * h, (-0.7, -0.6, 0.45), col(0.10, 0.28, 0.55),
                              col(0.35, 0.72, 1.0), 2.0, rng, bands=1.0, glow_gain=1.3)
        img = img * (1 - cv) + colr * cv + gl
    elif kind == "known-planet":     # a dark planet with a warm ring
        colr, cv, gl = planet(h, w, 0.50 * w, 0.52 * h, 0.22 * h, (0.6, -0.6, 0.5), col(0.07, 0.07, 0.10),
                              col(1.0, 0.66, 0.32), 1.8, rng, bands=0.6, glow_gain=1.0)
        rot = -0.22
        u = (xx - 0.5 * w) * math.cos(rot) + (yy - 0.52 * h) * math.sin(rot)
        v = -(xx - 0.5 * w) * math.sin(rot) + (yy - 0.52 * h) * math.cos(rot)
        f = np.hypot(u / (0.52 * h * 1.6), v / (0.52 * h * 1.6 * 0.19))
        ringm = smooth(0.62, 0.66, f) * (1 - smooth(0.96, 1.0, f)) * (0.55 + 0.45 * np.sin(f * 55))
        ringc = ringm[..., None] * col(1.0, 0.72, 0.38) * 0.9
        inside = (cv[..., 0] > 0.5)
        front = (v > 0)
        base = img * (1 - cv) + colr * cv + gl
        img = np.where((front | ~inside)[..., None], base + ringc, base)
    elif kind == "candidate":        # a bright blue star, partly eclipsed
        img += sun_flare(h, w, 0.50 * w, 0.50 * h, 26, col(0.50, 0.72, 1.0), 0.8, 0.5)
        colr, cv, gl = planet(h, w, 0.58 * w, 0.54 * h, 0.17 * h, (-0.9, -0.2, 0.2), col(0.01, 0.01, 0.03),
                              col(0.5, 0.74, 1.0), 1.0, rng, bands=0.0, glow_gain=0.0, night=0.0)
        img = img * (1 - cv) + colr * cv
    elif kind == "false-positive":   # a dramatic red star with flares
        colr, cv, gl = planet(h, w, 0.50 * w, 0.52 * h, 0.27 * h, (-0.3, -0.4, 0.8), col(0.95, 0.25, 0.08),
                              col(1.0, 0.35, 0.12), 2.6, rng, bands=1.4, glow_gain=1.9, night=0.35)
        img = img * (1 - cv) + colr * cv + gl * 1.4
        d = np.hypot(xx - 0.5 * w, yy - 0.52 * h)
        img += (np.exp(-np.clip(d - 0.27 * h, 0, None) / 26) * 0.55)[..., None] * col(1.0, 0.25, 0.08) * (d > 0.27 * h)[..., None]
    elif kind == "eclipsing-binary":  # a planet crossing a star, above an orbital horizon
        img += sun_flare(h, w, 0.62 * w, 0.40 * h, 20, col(1.0, 0.70, 0.36), 0.9, 0.4)
        colr, cv, gl = planet(h, w, 0.60 * w, 0.40 * h, 0.075 * h * 2, (-0.9, -0.1, 0.1), col(0.01, 0.01, 0.02),
                              col(1.0, 0.6, 0.3), 1.0, rng, bands=0.0, glow_gain=0.0, night=0.0)
        img = img * (1 - cv) + colr * cv
        hc, hg, hl = planet(h, w, 0.46 * w, 2.15 * h, 1.45 * h, (0.4, -0.9, 0.2), col(0.04, 0.07, 0.12),
                            col(0.35, 0.65, 1.0), 2.0, rng, bands=0.6, glow_gain=1.2)
        img = img * (1 - hg) + hc * hg + hl
    elif kind == "models-split":     # two stars the classifiers disagree about
        img += sun_flare(h, w, 0.36 * w, 0.52 * h, 17, col(0.45, 0.68, 1.0), 0.7, 0.4)
        img += sun_flare(h, w, 0.66 * w, 0.50 * h, 17, col(1.0, 0.66, 0.30), 0.7, 0.4)
    elif kind == "catalogs-down":    # a warm star behind a dark, hazy void
        img += sun_flare(h, w, 0.50 * w, 0.46 * h, 14, col(1.0, 0.72, 0.40), 0.6, 0.3)
        fog = fbm(h, w, rng, octaves=5, base=2)
        img *= (1 - 0.55 * smooth(0.45, 0.8, fog))[..., None]
    else:                            # "no-signal": a quiet star, nothing else
        img += sun_flare(h, w, 0.50 * w, 0.50 * h, 9, col(0.95, 0.90, 0.80), 0.25, 0.15) * 0.8
    img *= vignette_fade(h, w, left=0.02, r=0.02, t=0.02, b=0.02)
    return tonemap(img, 1.0, rng)


SCENES = {
    "space-background": (scene_background, 71, 2),
    "hero-planetary-horizon": (scene_hero, 11, 3),
    "candidates-accretion-disk": (scene_candidates, 12, 4),
    "sky-galaxy-horizon": (scene_sky, 13, 5),
    "models-planet-horizon": (scene_models, 14, 6),
    "lab-orbital-structure": (scene_lab, 15, 7),
    "images-spiral-galaxy": (scene_galaxy_image, 16, 8),
}
CASES = ["clean-transit", "known-planet", "candidate", "false-positive", "eclipsing-binary",
         "models-split", "catalogs-down", "no-signal"]


def save(arr: np.ndarray, path: Path, q: int) -> None:
    Image.fromarray(arr, "RGB").save(path, "WEBP", quality=q, method=6)
    print(f"{path.name:36s} {arr.shape[1]}x{arr.shape[0]}  {path.stat().st_size / 1024:6.0f} kB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="frontend/public/assets/space")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, (fn, seed, _) in SCENES.items():
        if a.only and not any(o in name for o in a.only):
            continue
        save(fn(np.random.default_rng(seed)), out / f"{name}.webp", 80)
    for i, k in enumerate(CASES):
        if a.only and not any(o in f"case-{k}" for o in a.only):
            continue
        save(thumb(k, np.random.default_rng(100 + i)), out / f"case-{k}.webp", 82)


if __name__ == "__main__":
    main()
