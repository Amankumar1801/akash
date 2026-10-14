import io
import json
import sqlite3
import tarfile

import pytest
from akash_api.app import create_app
from akash_api.backup import BackupError, create_backup, restore_backup
from akash_core.config import Settings
from akash_core.preflight import ConfigError, check, enforce
from fastapi.testclient import TestClient


def codes(s, level=None):
    return {f.code for f in check(s) if level is None or f.level == level}


def S(tmp_path, **kw):
    return Settings(env="prod", data_dir=str(tmp_path), sqlite_path=str(tmp_path / "a.db"),
                    registry_root=str(tmp_path / "reg"), contact_email="me@example.org", **kw)


# ---------- preflight ----------
def test_clean_prod_config_has_no_errors(tmp_path):
    assert codes(S(tmp_path), "error") == set()


@pytest.mark.parametrize("kw,code", [
    ({"api_cors_origins": "*"}, "cors_wildcard"),
    ({"api_cors_origins": "http://app.example.org"}, "cors_http"),
    ({"transit_model": "nope"}, "transit_model"),
    ({"transit_model": "m/v1"}, "transit_model_missing"),
    ({"anomaly_reference": "/no/such/file"}, "anomaly_reference_missing"),
    ({"llm_api_key": "k"}, "llm_model"),
    ({"llm_api_key": "k", "llm_model": "m", "llm_base_url": "http://x"}, "llm_https"),
    ({"api_rate_per_min": 0}, "limit_api_rate_per_min"),
])
def test_prod_errors(tmp_path, kw, code):
    assert code in codes(S(tmp_path, **kw), "error")


def test_unknown_env_and_unwritable_data_dir(tmp_path):
    f = tmp_path / "file"
    f.write_text("x")
    assert "bad_env" in codes(Settings(env="production", data_dir=str(tmp_path)), "error")
    assert "data_dir" in codes(Settings(env="dev", data_dir=str(f / "sub")), "error")


def test_dev_tolerates_what_prod_refuses(tmp_path):
    s = Settings(env="dev", data_dir=str(tmp_path), sqlite_path=str(tmp_path / "a.db"),
                 api_cors_origins="*")
    assert "cors_wildcard" in codes(s, "warning")
    assert enforce(s)  # does not raise


def test_enforce_raises_in_prod_and_never_leaks_secrets(tmp_path):
    with pytest.raises(ConfigError) as e:
        enforce(S(tmp_path, llm_api_key="sk-very-secret", api_cors_origins="*"))
    assert "sk-very-secret" not in str(e.value) and "cors_wildcard" in str(e.value)
    with pytest.raises(ConfigError):
        create_app(S(tmp_path, api_cors_origins="*"), None)


def test_warnings_do_not_block_prod(tmp_path):
    s = Settings(env="prod", data_dir=str(tmp_path), sqlite_path=str(tmp_path / "a.db"))
    assert {"no_classifier", "contact_email"} <= codes(s, "warning")
    enforce(s)


# ---------- readiness ----------
def test_ready_reports_database_and_is_unauthenticated(client):
    r = client.get("/v1/ready")
    assert r.status_code == 200 and r.json()["checks"]["database"] == "ok"
    assert r.json()["status"] == "ready"


def test_unconfigured_service_is_not_ready_but_alive(tmp_path):
    with TestClient(create_app(Settings(env="test", data_dir=str(tmp_path)), None)) as c:
        assert c.get("/v1/health").status_code == 200
        assert c.get("/v1/ready").status_code == 503


def test_ready_goes_unready_when_the_database_breaks(services, settings, keys):
    from unittest.mock import patch
    with TestClient(create_app(settings, services)) as c, patch.object(
            type(services), "context", side_effect=sqlite3.OperationalError("disk")):
        r = c.get("/v1/ready")
    assert r.status_code == 503 and r.json()["checks"]["database"] == "unavailable"
    assert "disk" not in r.text


# ---------- backup / restore ----------
def make_state(tmp_path):
    db, arts = tmp_path / "live.db", tmp_path / "objs"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE t(x)")
    c.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(50)])
    c.commit()
    c.close()
    (arts / "ab").mkdir(parents=True)
    (arts / "ab" / "cd.npz").write_bytes(b"artifact-bytes")
    return db, arts


def test_roundtrip_restores_database_and_artifacts(tmp_path):
    db, arts = make_state(tmp_path)
    out = tmp_path / "b" / "x.tar.gz"
    assert create_backup(db, arts, out)["files"] == 2 and out.exists()
    assert not list(out.parent.glob("*.part"))
    db2, arts2 = tmp_path / "new" / "r.db", tmp_path / "new" / "objs"
    assert restore_backup(out, db2, arts2)["artifacts"] == 1
    assert sqlite3.connect(db2).execute("SELECT COUNT(*) FROM t").fetchone()[0] == 50
    assert (arts2 / "ab" / "cd.npz").read_bytes() == b"artifact-bytes"


def test_backup_is_consistent_while_writing(tmp_path):
    db, arts = make_state(tmp_path)
    writer = sqlite3.connect(db)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO t VALUES (999)")  # uncommitted write in flight
    create_backup(db, arts, tmp_path / "x.tar.gz")
    writer.rollback()
    restore_backup(tmp_path / "x.tar.gz", tmp_path / "r.db", tmp_path / "o")
    assert sqlite3.connect(tmp_path / "r.db").execute("SELECT COUNT(*) FROM t").fetchone()[0] == 50


def test_restore_will_not_overwrite_by_default(tmp_path):
    db, arts = make_state(tmp_path)
    create_backup(db, arts, tmp_path / "x.tar.gz")
    with pytest.raises(BackupError):
        restore_backup(tmp_path / "x.tar.gz", db, arts)
    restore_backup(tmp_path / "x.tar.gz", db, arts, overwrite=True)


def rewrite(src, dst, mutate):
    with tarfile.open(src) as t:
        items = [(m, t.extractfile(m).read()) for m in t.getmembers()]
    with tarfile.open(dst, "w:gz") as t:
        for m, data in mutate(items):
            m.size = len(data)
            t.addfile(m, io.BytesIO(data))


def test_tampered_artifact_is_detected_and_nothing_is_written(tmp_path):
    db, arts = make_state(tmp_path)
    create_backup(db, arts, tmp_path / "x.tar.gz")
    rewrite(tmp_path / "x.tar.gz", tmp_path / "bad.tar.gz",
            lambda items: [(m, b"tampered" if m.name.endswith("npz") else d) for m, d in items])
    with pytest.raises(BackupError, match="hash mismatch"):
        restore_backup(tmp_path / "bad.tar.gz", tmp_path / "r.db", tmp_path / "o")
    assert not (tmp_path / "r.db").exists() and not (tmp_path / "o").exists()


def test_path_traversal_and_missing_manifest_are_refused(tmp_path):
    db, arts = make_state(tmp_path)
    create_backup(db, arts, tmp_path / "x.tar.gz")

    def evil(items):
        out = []
        for m, d in items:
            if m.name == "manifest.json":
                man = json.loads(d)
                man["files"]["../../escape.txt"] = "0" * 64
                d = json.dumps(man).encode()
            out.append((m, d))
        m = tarfile.TarInfo("../../escape.txt")
        return [*out, (m, b"x")]
    rewrite(tmp_path / "x.tar.gz", tmp_path / "evil.tar.gz", evil)
    with pytest.raises(BackupError, match="unsafe"):
        restore_backup(tmp_path / "evil.tar.gz", tmp_path / "r.db", tmp_path / "o")
    assert not (tmp_path.parent / "escape.txt").exists()
    rewrite(tmp_path / "x.tar.gz", tmp_path / "nomanifest.tar.gz",
            lambda items: [(m, d) for m, d in items if m.name != "manifest.json"])
    with pytest.raises(BackupError):
        restore_backup(tmp_path / "nomanifest.tar.gz", tmp_path / "r.db", tmp_path / "o")


def test_extra_or_missing_files_versus_manifest_are_refused(tmp_path):
    db, arts = make_state(tmp_path)
    create_backup(db, arts, tmp_path / "x.tar.gz")
    rewrite(tmp_path / "x.tar.gz", tmp_path / "missing.tar.gz",
            lambda items: [(m, d) for m, d in items if not m.name.endswith("npz")])
    with pytest.raises(BackupError, match="manifest"):
        restore_backup(tmp_path / "missing.tar.gz", tmp_path / "r.db", tmp_path / "o")


def test_missing_database_is_an_error(tmp_path):
    with pytest.raises(BackupError):
        create_backup(tmp_path / "none.db", tmp_path, tmp_path / "x.tar.gz")
