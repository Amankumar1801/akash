"""Back up or restore the service's database and artifacts.

    uv run python scripts/backup.py create --out backups/akash-$(date +%F).tar.gz
    uv run python scripts/backup.py restore backups/akash-2026-10-14.tar.gz [--overwrite]
Stop the service before a restore."""

from __future__ import annotations

import argparse
from pathlib import Path

from akash_api.backup import create_backup, restore_backup
from akash_core.config import Settings


def main() -> None:
    s = Settings()
    arts = Path(s.data_dir) / "objects"
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--out", required=True)
    r = sub.add_parser("restore")
    r.add_argument("archive")
    r.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()
    if a.cmd == "create":
        print(create_backup(s.sqlite_path, arts, a.out))
    else:
        print(restore_backup(a.archive, s.sqlite_path, arts, a.overwrite))


if __name__ == "__main__":
    main()
