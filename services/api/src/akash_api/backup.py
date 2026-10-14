"""Backup and restore of everything the service owns: the SQLite database (consistent online
copy) and the artifact files, in one tar.gz with a manifest of sha256 hashes.

Restore verifies every hash before writing anything, refuses archive members that could escape
the target directory, and refuses to overwrite an existing database unless told to."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import sqlite3
import tarfile
import tempfile
import time
from pathlib import Path

MANIFEST = "manifest.json"
DB_NAME = "akash.sqlite3"


class BackupError(Exception):
    pass


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def create_backup(db_path: str | Path, artifacts_dir: str | Path,
                  out: str | Path) -> dict[str, object]:
    db_path, artifacts_dir, out = Path(db_path), Path(artifacts_dir), Path(out)
    if not db_path.is_file():
        raise BackupError("database not found")
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / DB_NAME
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        dst = sqlite3.connect(snap)
        try:
            src.backup(dst)  # consistent even while the service is writing
        finally:
            dst.close()
            src.close()
        files: dict[str, str] = {f"db/{DB_NAME}": _sha(snap)}
        arts = (sorted(p for p in artifacts_dir.rglob("*") if p.is_file())
                if artifacts_dir.is_dir() else [])
        for p in arts:
            files[f"artifacts/{p.relative_to(artifacts_dir).as_posix()}"] = _sha(p)
        manifest = {"created_at": time.time(), "format": 1, "files": files}
        out.parent.mkdir(parents=True, exist_ok=True)
        part = out.with_suffix(out.suffix + ".part")
        with tarfile.open(part, "w:gz") as tar:
            tar.add(snap, arcname=f"db/{DB_NAME}")
            for p in arts:
                tar.add(p, arcname=f"artifacts/{p.relative_to(artifacts_dir).as_posix()}")
            raw = json.dumps(manifest, sort_keys=True).encode()
            info = tarfile.TarInfo(MANIFEST)
            info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))
        part.replace(out)  # a half-written archive never has the final name
    return {"files": len(files), "path": str(out)}


def _safe(name: str) -> bool:
    p = Path(name)
    return not p.is_absolute() and ".." not in p.parts and name != ""


def restore_backup(archive: str | Path, db_path: str | Path, artifacts_dir: str | Path,
                   overwrite: bool = False) -> dict[str, object]:
    archive, db_path, artifacts_dir = Path(archive), Path(db_path), Path(artifacts_dir)
    if db_path.exists() and not overwrite:
        raise BackupError("database already exists; pass overwrite to replace it")
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        for m in members:
            if not m.isfile() or not _safe(m.name):
                raise BackupError(f"unsafe archive member: {m.name!r}")
        try:
            manifest = json.loads(tar.extractfile(MANIFEST).read())  # type: ignore[union-attr]
        except (KeyError, AttributeError, ValueError):
            raise BackupError("missing or unreadable manifest") from None
        want: dict[str, str] = manifest["files"]
        have = {m.name for m in members} - {MANIFEST}
        if have != set(want):
            raise BackupError("archive contents do not match the manifest")
        root = Path(tmp)
        for m in members:
            if m.name != MANIFEST:
                tar.extract(m, root, filter="data")
        for name, digest in want.items():
            if _sha(root / name) != digest:
                raise BackupError(f"hash mismatch: {name}")
        check = sqlite3.connect(root / "db" / DB_NAME)
        try:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("restored database failed its integrity check")
        finally:
            check.close()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / "db" / DB_NAME, db_path)
        n = 0
        for name in want:
            if name.startswith("artifacts/"):
                dest = artifacts_dir / name[len("artifacts/"):]
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / name, dest)
                n += 1
    return {"db": str(db_path), "artifacts": n}
