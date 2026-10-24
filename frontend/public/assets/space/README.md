# Space imagery

Every file here is an **illustration rendered by `scripts/make_space_assets.py`** (numpy: limb-darkened
spheres, atmospheric rim light, log-spiral galaxies, bloom). They are **not photographs and not
observations**, and none of them depicts a real target. They carry no third-party licence: they are
generated from the code in this repository (deterministic seeds, so they rebuild identically).

Rebuild: `python scripts/make_space_assets.py` (needs numpy, scipy, Pillow).

| File | Used by |
|---|---|
| `space-background.webp` | global deep-space layer behind every page |
| `hero-planetary-horizon.webp` | Logbook hero |
| `candidates-accretion-disk.webp` | Candidates |
| `sky-galaxy-horizon.webp` | Sky |
| `models-planet-horizon.webp` | Models |
| `lab-orbital-structure.webp` | Lab |
| `images-spiral-galaxy.webp` | Images (empty state) |
| `case-*.webp` | thumbnails for the synthetic cases and candidate cards |

## Using a real NASA/ESA photograph instead
Drop a file with the **same name** into this folder (any size; WebP, or change the extension in
`src/styles.css`). Keep the picture dark around its edges: the scenes are blended with `screen`, so
black becomes transparent. NASA media is generally free to use with credit; check the specific
image's page, and do not present a stock image as an observation of a particular TIC target.
