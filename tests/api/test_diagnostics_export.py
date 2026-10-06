"""Tests for the database snapshot, diagnostics bundle and raw config download."""

import asyncio
import io
import json
import sqlite3
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.deps import get_learning_store
from backend.api.routers import config as config_router
from backend.api.routers import system as system_router

CONFIG_BYTES = b"# comment kept\nzeta: 1\nalpha:   2\nhome_assistant:\n  url: http://ha\n"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Working dir with data/, config.yaml and a WAL database holding rows that live only in the WAL."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "config.yaml").write_bytes(CONFIG_BYTES)
    (tmp_path / "data" / "darkstar.log").write_text("log line\n")
    (tmp_path / "data" / "schedule.json").write_text('{"schedule": []}')

    db_path = tmp_path / "data" / "planner_learning.db"
    # Keep this connection open so the WAL is not checkpointed on close.
    live = sqlite3.connect(db_path)
    live.execute("PRAGMA journal_mode=WAL")
    live.execute("PRAGMA wal_autocheckpoint=0")
    live.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    live.executemany("INSERT INTO t (v) VALUES (?)", [(f"row{i}",) for i in range(50)])
    live.commit()

    async def ok_status():
        return {"status": "online"}

    async def ok_health():
        return {"ok": True}

    async def ok_monitors():
        return {"monitors": []}

    monkeypatch.setattr(system_router, "get_system_status", ok_status)
    monkeypatch.setattr(system_router, "get_system_health", ok_health)
    monkeypatch.setattr(system_router, "get_invariant_monitors", ok_monitors)

    app = FastAPI()
    app.include_router(system_router.router)
    app.include_router(config_router.router)
    app.dependency_overrides[get_learning_store] = lambda: SimpleNamespace(db_path=str(db_path))
    client = TestClient(app)
    yield SimpleNamespace(root=tmp_path, db_path=db_path, live=live, client=client)
    live.close()


def _leftovers(root: Path) -> list[str]:
    return [p.name for p in (root / "data").iterdir() if p.name.startswith(".")]


def _assert_valid_copy(data: bytes, tmp: Path) -> None:
    copy = tmp / "copy.db"
    copy.write_bytes(data)
    conn = sqlite3.connect(copy)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone() == (50,)
    finally:
        conn.close()


def test_snapshot_valid_with_wal_rows_and_live_db_unchanged(env, tmp_path_factory):
    wal = Path(f"{env.db_path}-wal")
    assert wal.exists()
    assert wal.stat().st_size > 0  # rows live only in the WAL
    before = env.live.execute("SELECT COUNT(*) FROM t").fetchone()

    resp = env.client.get("/api/system/db-snapshot")

    assert resp.status_code == 200
    assert "planner_learning-" in resp.headers["content-disposition"]
    _assert_valid_copy(resp.content, tmp_path_factory.mktemp("copy"))
    assert env.live.execute("SELECT COUNT(*) FROM t").fetchone() == before
    assert _leftovers(env.root) == []


def test_snapshot_missing_db_errors_without_leftovers(env):
    env.live.close()
    for p in env.root.joinpath("data").glob("planner_learning.db*"):
        p.unlink()

    resp = env.client.get("/api/system/db-snapshot")

    assert resp.status_code == 404
    assert _leftovers(env.root) == []


def test_concurrent_requests_get_409(env, monkeypatch):
    lock = asyncio.Lock()
    asyncio.run(lock.acquire())
    monkeypatch.setattr(system_router, "_export_lock", lock)

    assert env.client.get("/api/system/db-snapshot").status_code == 409
    assert env.client.get("/api/system/diagnostics").status_code == 409


def test_bundle_contents(env, tmp_path_factory):
    resp = env.client.get("/api/system/diagnostics")

    assert resp.status_code == 200
    assert "darkstar-diagnostics-" in resp.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert set(zf.namelist()) == {
        "planner_learning.db",
        "config.yaml",
        "darkstar.log",
        "schedule.json",
        "version.json",
        "status.json",
        "health.json",
        "monitors.json",
        "manifest.json",
    }
    assert zf.read("config.yaml") == CONFIG_BYTES
    _assert_valid_copy(zf.read("planner_learning.db"), tmp_path_factory.mktemp("copy"))
    assert not any("secrets" in n for n in zf.namelist())
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["version"]
    assert manifest["exported_at_utc"].endswith("+00:00")
    assert set(manifest["items"].values()) == {"included"}
    assert _leftovers(env.root) == []


def test_bundle_never_reads_secrets(env, monkeypatch):
    (env.root / "secrets.yaml").write_text("home_assistant:\n  token: SECRET\n")
    real_open = Path.read_bytes

    def guard(self, *a, **k):
        assert self.name != "secrets.yaml"
        return real_open(self, *a, **k)

    monkeypatch.setattr(Path, "read_bytes", guard)
    resp = env.client.get("/api/system/diagnostics")
    assert resp.status_code == 200
    assert b"SECRET" not in resp.content


def test_bundle_survives_missing_schedule_and_failing_status(env, monkeypatch):
    (env.root / "data" / "schedule.json").unlink()

    async def boom():
        raise RuntimeError("HA unreachable")

    monkeypatch.setattr(system_router, "get_system_status", boom)

    resp = env.client.get("/api/system/diagnostics")

    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert "schedule.json" not in zf.namelist()
    assert "status.json" not in zf.namelist()
    items = json.loads(zf.read("manifest.json"))["items"]
    assert "not found" in items["schedule.json"]
    assert "HA unreachable" in items["status.json"]
    assert items["planner_learning.db"] == "included"


def test_config_download_is_raw_file_and_ignores_secrets(env, monkeypatch):
    (env.root / "secrets.yaml").write_text("home_assistant:\n  token: SECRET\n")
    real_open = Path.read_bytes

    def guard(self, *a, **k):
        assert self.name != "secrets.yaml"
        return real_open(self, *a, **k)

    monkeypatch.setattr(Path, "read_bytes", guard)
    monkeypatch.setattr(
        config_router,
        "load_yaml",
        lambda *a, **k: pytest.fail("download must not parse config or secrets"),
    )

    resp = env.client.get("/api/config/download")

    assert resp.status_code == 200
    assert resp.content == CONFIG_BYTES


def test_config_download_missing_is_404(env):
    (env.root / "config.yaml").unlink()
    assert env.client.get("/api/config/download").status_code == 404
