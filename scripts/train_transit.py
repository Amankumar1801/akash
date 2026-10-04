"""Train + evaluate the transit classifier system and write registry entry, evaluation JSON and
model card.

  # plumbing validation on SYNTHETIC data (not science):
  uv run python scripts/train_transit.py --synthetic 320 --name transit-synthetic
  # real run:
  uv run python scripts/train_transit.py --dataset data/kepler_dr25.npz --name transit-kepler \
      --manifest evaluation/kepler_split_manifest.json --salt akash-kepler-v1

The split manifest is FROZEN: once written it is only ever extended (hash-based assignment means
existing stars never move), so the test set cannot silently drift between model versions.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import warnings
from pathlib import Path

from akash_ml.model_card import render_model_card
from akash_ml.registry import save_system
from akash_ml.training import TrainConfig, train_system
from akash_ml.transit.dataset import TransitDataset
from akash_ml.transit.splits import SplitManifest
from akash_ml.transit.synthetic_set import make_synthetic_transit_dataset


def code_version() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def main() -> None:
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--synthetic", type=int, metavar="N_STARS")
    g.add_argument("--dataset", type=Path)
    ap.add_argument("--name", required=True)
    ap.add_argument("--version", default="v1")
    ap.add_argument("--salt", default="akash-v1")
    ap.add_argument("--manifest", type=Path, default=None)
    ap.add_argument("--models-dir", type=Path, default=Path("models"))
    ap.add_argument("--n-cnn", type=int, default=5)
    ap.add_argument("--cnn-epochs", type=int, default=40)
    ap.add_argument("--no-cnn", action="store_true")
    a = ap.parse_args()

    if a.synthetic:
        ds, note = (make_synthetic_transit_dataset(a.synthetic, seed=1),
                    "SYNTHETIC plumbing-validation data (NOT real astronomical data; metrics "
                    "show the machinery works, not that the science does)")
    else:
        ds, note = TransitDataset.load(a.dataset), f"catalog TCEs from {a.dataset.name}"

    if a.manifest and a.manifest.exists():
        man = SplitManifest.from_json(json.loads(a.manifest.read_text()))  # verifies digest
        new = set(map(int, ds.star_ids)) - set(man.assignment)
        if new:
            ext = SplitManifest.build(set(man.assignment) | new, man.salt, man.fractions)
            assert all(ext.assignment[k] == v for k, v in man.assignment.items())  # frozen
            man = ext
            a.manifest.write_text(json.dumps(man.to_json()))
            print(f"extended manifest with {len(new)} new stars (existing assignments unchanged)")
    else:
        man = SplitManifest.build(ds.star_ids, a.salt)
        if a.manifest:
            a.manifest.parent.mkdir(parents=True, exist_ok=True)
            a.manifest.write_text(json.dumps(man.to_json()))

    cfg = TrainConfig(n_cnn=a.n_cnn, cnn_epochs=a.cnn_epochs, run_cnn=not a.no_cnn)
    system = train_system(ds, man, cfg, code_version())
    d = save_system(a.models_dir, a.name, a.version, system)
    meta = json.loads((d / "metadata.json").read_text())
    card = render_model_card(meta, note)
    (d / "MODEL_CARD.md").write_text(card)
    Path("evaluation").mkdir(exist_ok=True)
    (Path("evaluation") / f"{a.name}-{a.version}.json").write_text(
        json.dumps(meta["metrics"], indent=1, default=float))
    print(card)
    print(f"\nsaved {d}")


if __name__ == "__main__":
    main()
