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
from backend.api.routers import config as config_router, system as system_router

REAL_BALANCER_TRACE = system_router._get_balancer_trace

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

    async def ok_trace():
        return {"max_ticks": 600, "ticks": []}

    monkeypatch.setattr(system_router, "get_system_status", ok_status)
    monkeypatch.setattr(system_router, "_get_balancer_trace", ok_trace)
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
        "balancer_trace.json",
        "manifest.json",
    }
    assert zf.read("config.yaml") == CONFIG_BYTES  # nothing to redact: byte-identical
    _assert_valid_copy(zf.read("planner_learning.db"), tmp_path_factory.mktemp("copy"))
    assert not any("secrets" in n for n in zf.namelist())
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["version"]
    assert manifest["exported_at_utc"].endswith("+00:00")
    assert manifest["redacted"] is True
    assert set(manifest["items"].values()) == {"included"}
    assert _leftovers(env.root) == []


def test_bundle_includes_rotated_log_when_present(env):
    (env.root / "data" / "darkstar.log.1").write_text("older line\n")

    resp = env.client.get("/api/system/diagnostics")

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert zf.read("darkstar.log.1") == b"older line\n"
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["items"]["darkstar.log.1"] == "included"


def test_clear_logs_truncates_active_log_and_removes_backups(env):
    data = env.root / "data"
    (data / "darkstar.log").write_text("active\n")
    for n in range(1, 6):
        (data / f"darkstar.log.{n}").write_text("old\n")
    legacy = data / "darkstar.log.2020-01-01"
    legacy.write_text("legacy\n")

    resp = env.client.delete("/api/system/logs")

    assert resp.status_code == 200
    assert (data / "darkstar.log").read_text() == ""
    assert [p.name for p in data.glob("darkstar.log.[0-9]")] == []
    assert legacy.exists()


def test_clear_logs_without_backups(env):
    resp = env.client.delete("/api/system/logs")

    assert resp.status_code == 200
    assert (env.root / "data" / "darkstar.log").read_text() == ""


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


def test_config_download_stays_raw_with_secrets_and_coordinates(env):
    raw = b"latitude: 55.123\napi_key: abc\nurl: https://myhome.ui.nabu.casa/x\n"
    (env.root / "config.yaml").write_bytes(raw)

    assert env.client.get("/api/config/download").content == raw


def test_log_download_is_redacted_and_temp_file_removed(env):
    log = env.root / "data" / "darkstar.log"
    log.write_text(
        "GET https://myhome.ui.nabu.casa/api/states?token=abc from 8.8.8.8\n"
        "connected http://192.168.0.100:8123\n"
    )

    resp = env.client.get("/api/system/logs")

    assert resp.status_code == 200
    text = resp.text
    assert "nabu.casa" not in text
    assert "token=abc" not in text
    assert "8.8.8.8" not in text
    assert "<redacted-host>" in text
    assert "http://192.168.0.100:8123" in text
    assert text.count("\n") == 2
    assert _leftovers(env.root) == []
    assert "nabu.casa" in log.read_text()  # source log stays raw


def test_log_download_is_read_incrementally(env, monkeypatch):
    calls: list[str] = []
    real = system_router.redact_text
    monkeypatch.setattr(system_router, "redact_text", lambda t: (calls.append(t), real(t))[1])
    (env.root / "data" / "darkstar.log").write_text("one\ntwo\nthree\n")

    assert env.client.get("/api/system/logs").text == "one\ntwo\nthree\n"
    assert calls == ["one\n", "two\n", "three\n"]


def test_log_download_failure_leaves_no_temp_file(env, monkeypatch):
    def boom(_t):
        raise RuntimeError("boom")

    monkeypatch.setattr(system_router, "redact_text", boom)
    client = TestClient(env.client.app, raise_server_exceptions=False)

    assert client.get("/api/system/logs").status_code == 500
    assert _leftovers(env.root) == []


def test_log_download_missing_is_404(env):
    (env.root / "data" / "darkstar.log").unlink()
    assert env.client.get("/api/system/logs").status_code == 404


def test_config_download_missing_is_404(env):
    (env.root / "config.yaml").unlink()
    assert env.client.get("/api/config/download").status_code == 404


def test_bundle_includes_the_balancer_trace(env, monkeypatch):
    ticks = [{"t": "2026-10-21T12:00:00", "state": "throttling"}]
    fake_executor = SimpleNamespace(get_balancer_trace=lambda: ticks)
    monkeypatch.setattr(system_router, "_get_balancer_trace", REAL_BALANCER_TRACE)
    monkeypatch.setattr("backend.api.routers.executor.get_executor_instance", lambda: fake_executor)

    resp = env.client.get("/api/system/diagnostics")

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    trace = json.loads(zf.read("balancer_trace.json"))
    assert trace["ticks"] == ticks
    assert trace["max_ticks"] == 600
    assert json.loads(zf.read("manifest.json"))["items"]["balancer_trace.json"] == "included"


def test_bundle_survives_a_failing_balancer_trace(env, monkeypatch):
    monkeypatch.setattr(system_router, "_get_balancer_trace", REAL_BALANCER_TRACE)
    monkeypatch.setattr("backend.api.routers.executor.get_executor_instance", lambda: None)

    resp = env.client.get("/api/system/diagnostics")

    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert "balancer_trace.json" not in zf.namelist()
    items = json.loads(zf.read("manifest.json"))["items"]
    assert "executor unavailable" in items["balancer_trace.json"]
    assert items["planner_learning.db"] == "included"
    assert items["status.json"] == "included"


def _bundle(env) -> zipfile.ZipFile:
    resp = env.client.get("/api/system/diagnostics")
    assert resp.status_code == 200
    return zipfile.ZipFile(io.BytesIO(resp.content))


def test_bundle_redacts_config(env):
    (env.root / "config.yaml").write_text(
        "# keep me\nsystem:\n  latitude: 55.123\n  longitude: 13.456\n"
        "api_key: abc\nempty_token: ''\nsensor: sensor.battery_soc\n"
        "notifications:\n  discord_webhook: https://discord.com/api/webhooks/1/x\n"
    )

    text = _bundle(env).read("config.yaml").decode()

    assert "# keep me" in text
    assert "abc" not in text
    assert "webhooks/1" not in text
    assert text.count("<redacted>") == 2
    assert "55.1" in text
    assert "55.123" not in text
    assert "13.5" in text
    assert "sensor.battery_soc" in text


def test_bundle_unparseable_config_is_omitted_never_raw(env):
    (env.root / "config.yaml").write_text("a: [unclosed\n  token: SECRETVALUE\n")

    resp = env.client.get("/api/system/diagnostics")

    assert resp.status_code == 200
    assert b"SECRETVALUE" not in resp.content
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert "config.yaml" not in zf.namelist()
    items = json.loads(zf.read("manifest.json"))["items"]
    assert items["config.yaml"] == "error: could not redact config"
    assert items["darkstar.log"] == "included"


def test_bundle_redacts_logs_line_by_line(env):
    line = "GET https://myhome.ui.nabu.casa/api/states?token=abc from 8.8.8.8\n"
    keep = "connected http://192.168.0.100:8123\n"
    (env.root / "data" / "darkstar.log").write_text(line + keep)
    (env.root / "data" / "darkstar.log.1").write_text(line)

    zf = _bundle(env)

    for name in ("darkstar.log", "darkstar.log.1"):
        text = zf.read(name).decode()
        assert "nabu.casa" not in text
        assert "token=abc" not in text
        assert "8.8.8.8" not in text
    assert "http://192.168.0.100:8123" in zf.read("darkstar.log").decode()
    assert zf.read("darkstar.log").decode().count("\n") == 2


def test_bundle_log_is_read_incrementally(env, monkeypatch):
    calls: list[str] = []
    real = system_router.redact_text
    monkeypatch.setattr(system_router, "redact_text", lambda t: (calls.append(t), real(t))[1])
    (env.root / "data" / "darkstar.log").write_text("one\ntwo\nthree\n")
    (env.root / "data" / "schedule.json").unlink()

    _bundle(env)

    assert [c for c in calls if c in ("one\n", "two\n", "three\n")] == ["one\n", "two\n", "three\n"]


def test_bundle_redacts_schedule_and_json_payloads(env, monkeypatch):
    (env.root / "data" / "schedule.json").write_text(
        '{"latitude": 55.123, "ha": "https://myhome.ui.nabu.casa/x"}'
    )

    async def leaky_status():
        return {"ha_url": "https://myhome.ui.nabu.casa/api?token=abc", "ip": "8.8.8.8"}

    monkeypatch.setattr(system_router, "get_system_status", leaky_status)

    zf = _bundle(env)

    schedule = zf.read("schedule.json").decode()
    assert "55.123" not in schedule
    assert "nabu.casa" not in schedule
    assert json.loads(schedule)["latitude"] == "<redacted>"
    status = zf.read("status.json").decode()
    assert "nabu.casa" not in status
    assert "token=abc" not in status
    assert "8.8.8.8" not in status
    json.loads(status)


def _add_config_versions(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE config_versions (id INTEGER PRIMARY KEY, yaml_blob TEXT)")
        conn.execute(
            "INSERT INTO config_versions (yaml_blob) VALUES (?)",
            ("api_key: SECRETKEY\nbattery:\n  capacity: 10\n",),
        )
        conn.commit()
    finally:
        conn.close()


def _rows(data: bytes, tmp: Path, sql: str) -> list[tuple]:
    copy = tmp / "rows.db"
    copy.write_bytes(data)
    conn = sqlite3.connect(copy)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_bundle_db_masks_config_version_secrets_standalone_stays_raw(env, tmp_path_factory):
    _add_config_versions(env.db_path)
    tmp = tmp_path_factory.mktemp("rows")

    bundle_db = _bundle(env).read("planner_learning.db")
    blob = _rows(bundle_db, tmp, "SELECT yaml_blob FROM config_versions")[0][0]
    assert "SECRETKEY" not in blob
    assert "<redacted>" in blob
    assert "capacity: 10" in blob
    # other tables equal the live DB
    assert (
        _rows(bundle_db, tmp, "SELECT id, v FROM t ORDER BY id")
        == env.live.execute("SELECT id, v FROM t ORDER BY id").fetchall()
    )

    # live DB and standalone snapshot keep the original
    assert "SECRETKEY" in env.live.execute("SELECT yaml_blob FROM config_versions").fetchone()[0]
    raw = env.client.get("/api/system/db-snapshot").content
    assert "SECRETKEY" in _rows(raw, tmp, "SELECT yaml_blob FROM config_versions")[0][0]
    assert _leftovers(env.root) == []


def test_bundle_omits_db_when_masking_fails(env, monkeypatch):
    def boom(_path):
        raise sqlite3.DatabaseError("boom")

    monkeypatch.setattr(system_router, "mask_config_versions", boom)

    resp = env.client.get("/api/system/diagnostics")

    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert "planner_learning.db" not in zf.namelist()
    items = json.loads(zf.read("manifest.json"))["items"]
    assert items["planner_learning.db"] == "error: could not mask config versions"
    assert items["config.yaml"] == "included"
    assert _leftovers(env.root) == []
