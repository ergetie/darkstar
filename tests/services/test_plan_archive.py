"""Plan archive module: retention parsing, capture, record writing, pruning, summary, zip."""

import asyncio
import gzip
import json
import os
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine

from backend.learning.models import Base
from backend.services import plan_archive as pa
from executor.history import ExecutionHistory, ExecutionRecord

NOW = datetime(2026, 11, 21, 12, 0, 0, tzinfo=UTC)
REQUIRED_KEYS = {
    "format_version",
    "run_id",
    "started_at",
    "finished_at",
    "outcome",
    "planner_version",
    "config_version",
    "config",
    "inputs",
    "schedule",
    "initial_soc_kwh",
    "initial_soc_percent",
    "safety_floor",
    "solver_status",
    "time_limit_hit",
    "error",
    "executor_errors",
    "executor_errors_truncated",
}


@pytest.fixture(autouse=True)
def isolated_db(tmp_path_factory, monkeypatch):
    """Point the executor-error lookup at a fresh database with the real schema."""
    path = tmp_path_factory.mktemp("db") / "learning.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    monkeypatch.setenv("DB_PATH", str(path))
    return path


def _stamp(moment: datetime, outcome: str = "ok") -> str:
    return f"{moment.strftime('%Y%m%dT%H%M%SZ')}-{outcome}.json.gz"


def _touch(directory: Path, moment: datetime, outcome: str = "ok", payload: bytes = b"x") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _stamp(moment, outcome)
    path.write_bytes(payload)
    return path


def _read(path: Path) -> dict:
    return json.loads(gzip.decompress(path.read_bytes()))


def _run(started: datetime = NOW) -> pa.RunCapture:
    run = pa.RunCapture(started_at=started)
    run.data.update(
        inputs={"price_data": [{"import_price_sek_kwh": 1.0}]},
        schedule={"schedule": [], "meta": {}},
        initial_soc_kwh=5.0,
        initial_soc_percent=37.0,
        safety_floor={"target_soc_kwh": 2.0},
        solver_status="Optimal",
        time_limit_hit=False,
    )
    return run


class TestRetentionParsing:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(60, 60), (7, 7), (3, 7), (0, 60), (-1, 60), ("abc", 60), (None, 60), (True, 60)],
    )
    def test_parse(self, value, expected):
        assert pa._parse_retention(value) == expected

    def test_numeric_string_and_float(self):
        assert pa._parse_retention("30") == 30
        assert pa._parse_retention(14.9) == 14


class TestCapture:
    def test_no_active_capture_is_noop(self):
        pa.capture("inputs", {"a": 1})  # must not raise

    def test_capture_snapshots_value(self):
        run = pa.start_capture()
        try:
            value = {"a": [1]}
            pa.capture("inputs", value)
            value["a"].append(2)
            assert run.data["inputs"] == {"a": [1]}
        finally:
            pa.end_capture()
        pa.capture("inputs", {"late": True})
        assert run.data["inputs"] == {"a": [1]}

    async def test_concurrent_tasks_are_isolated(self):
        results: dict[str, dict] = {}

        async def worker(name: str) -> None:
            run = pa.start_capture()
            try:
                await asyncio.sleep(0)
                pa.capture("who", name)
                await asyncio.sleep(0)
            finally:
                pa.end_capture()
            results[name] = run.data

        await asyncio.gather(worker("a"), worker("b"))
        assert results == {"a": {"who": "a"}, "b": {"who": "b"}}


class TestWriteRecord:
    async def test_record_has_all_keys(self, tmp_path):
        directory = tmp_path / "archive"
        config = {"config_version": 2, "debug": {"plan_archive_enabled": True}}
        path = await pa.write_record(_run(), "ok", None, config, directory)

        assert path is not None
        assert path.name == "20261121T120000Z-ok.json.gz"
        record = _read(path)
        assert set(record) == REQUIRED_KEYS
        assert record["format_version"] == 1
        assert record["outcome"] == "ok"
        assert record["config_version"] == 2
        assert record["executor_errors"] == []
        assert record["error"] is None
        assert [f.name for f in directory.iterdir()] == [path.name]

    async def test_error_record(self, tmp_path):
        error = {"code": "PRICES_UNAVAILABLE", "message": "no prices", "details": {"a": 1}}
        path = await pa.write_record(pa.RunCapture(started_at=NOW), "error", error, {}, tmp_path)
        assert path is not None
        assert path.name.endswith("-err.json.gz")
        record = _read(path)
        assert record["outcome"] == "error"
        assert record["error"] == error
        assert record["inputs"] == {}

    async def test_secret_config_value_removed(self, tmp_path):
        config = {
            "home_assistant": {"token": "SECRET-VALUE-123", "url": "http://192.168.1.2:8123"},
            "notifications": {"api_key": "KEY-ABC"},
        }
        path = await pa.write_record(_run(), "ok", None, config, tmp_path)
        raw = gzip.decompress(path.read_bytes()).decode()
        assert "SECRET-VALUE-123" not in raw
        assert "KEY-ABC" not in raw
        assert "token" not in _read(path)["config"]["home_assistant"]

    async def test_host_in_error_message_redacted(self, tmp_path):
        error = {"code": "X", "message": "failed https://my-secret.example.org/path", "details": None}
        path = await pa.write_record(pa.RunCapture(started_at=NOW), "error", error, {}, tmp_path)
        raw = gzip.decompress(path.read_bytes()).decode()
        assert "my-secret.example.org" not in raw
        assert "<redacted-host>" in raw

    async def test_unwritable_directory_returns_none(self, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("a file, not a directory")
        assert await pa.write_record(_run(), "ok", None, {}, blocker / "archive") is None

    async def test_no_temp_left_after_write_failure(self, tmp_path, monkeypatch):
        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(Path, "replace", boom)
        assert await pa.write_record(_run(), "ok", None, {}, tmp_path) is None
        assert list(tmp_path.iterdir()) == []

    async def test_disabled_writes_nothing_and_creates_no_directory(self, tmp_path):
        directory = tmp_path / "archive"
        config = {"debug": {"plan_archive_enabled": False}}
        assert await pa.write_record(_run(), "ok", None, config, directory) is None
        assert not directory.exists()

    async def test_executor_failures_land_only_in_second_record(self, tmp_path, isolated_db):
        directory = tmp_path / "archive"
        now = datetime.now(UTC).replace(microsecond=0)
        first_start = now - timedelta(minutes=30)
        _insert_failure(isolated_db, first_start - timedelta(minutes=1), "before first")
        # Logged while run A was still executing: belongs to A, must not repeat in B.
        _insert_failure(isolated_db, first_start + timedelta(minutes=5), "during first run")
        await pa.write_record(_run(first_start), "ok", None, {}, directory)
        _insert_failure(isolated_db, datetime.now(UTC) + timedelta(minutes=1), "between runs")
        await pa.write_record(_run(now), "ok", None, {}, directory)

        first, second = (_read(p) for p in sorted(directory.iterdir()))
        # First run: no earlier record, so the 24 h look-back applies.
        assert [e["error_message"] for e in first["executor_errors"]] == [
            "before first",
            "during first run",
        ]
        assert [e["error_message"] for e in second["executor_errors"]] == ["between runs"]
        assert second["executor_errors"][0]["slot_start"]
        assert second["executor_errors_truncated"] == 0

    async def test_since_uses_previous_finished_at_not_start(self, tmp_path):
        started = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=2)
        path = await pa.write_record(_run(started), "ok", None, {}, tmp_path)
        assert path is not None
        finished = datetime.fromisoformat(_read(path)["finished_at"])
        assert pa._since(tmp_path, finished) == finished

    async def test_since_falls_back_to_name_time_when_file_unreadable(self, tmp_path):
        started = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        _touch(tmp_path, started)
        assert pa._since(tmp_path, started + timedelta(hours=1)) == started

    async def test_lookup_failure_still_writes_record(self, tmp_path, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("db locked")

        monkeypatch.setattr(pa, "_load_executor_errors", boom)
        path = await pa.write_record(_run(), "ok", None, {}, tmp_path)
        assert path is not None
        assert _read(path)["executor_errors"] == []

    async def test_missing_database_gives_empty_errors(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "missing.db"))
        path = await pa.write_record(_run(), "ok", None, {}, tmp_path / "archive")
        assert _read(path)["executor_errors"] == []
        assert not (tmp_path / "missing.db").exists()

    async def test_write_prunes_old_records(self, tmp_path):
        now = datetime.now(UTC).replace(microsecond=0)
        old = _touch(tmp_path, now - timedelta(days=61))
        keep = _touch(tmp_path, now - timedelta(days=59))
        await pa.write_record(_run(now), "ok", None, {}, tmp_path)
        assert not old.exists()
        assert keep.exists()


def _insert_failure(db: Path, moment: datetime, message: str) -> None:
    # The executor stores local ISO text with the configured zone's offset.
    local = moment.astimezone(ZoneInfo("Europe/Stockholm")).isoformat()
    history = ExecutionHistory(str(db))
    history.log_execution(
        ExecutionRecord(
            executed_at=local,
            slot_start=local,
            success=0,
            error_message=message,
        )
    )
    history.engine.dispose()


class TestPrune:
    def test_old_deleted_recent_kept(self, tmp_path):
        old = _touch(tmp_path, NOW - timedelta(days=61))
        recent = _touch(tmp_path, NOW - timedelta(days=59), "err")
        assert pa.prune(60, NOW, tmp_path) == 1
        assert not old.exists()
        assert recent.exists()

    def test_unrelated_files_untouched(self, tmp_path):
        notes = tmp_path / "notes.txt"
        notes.write_text("keep")
        other = tmp_path / "20200101-ok.json.gz"
        other.write_bytes(b"x")
        pa.prune(60, NOW, tmp_path)
        assert notes.exists()
        assert other.exists()

    def test_stale_temp_files_deleted_fresh_kept(self, tmp_path):
        stale_tmp = tmp_path / ".20261121T000000Z-ok.json.gz.tmp"
        stale_zip = tmp_path / ".download-abc.zip"
        fresh_tmp = tmp_path / ".fresh.json.gz.tmp"
        for f in (stale_tmp, stale_zip, fresh_tmp):
            f.write_bytes(b"x")
        old = (NOW - timedelta(hours=2)).timestamp()
        os.utime(stale_tmp, (old, old))
        os.utime(stale_zip, (old, old))
        fresh = (NOW - timedelta(minutes=5)).timestamp()
        os.utime(fresh_tmp, (fresh, fresh))
        pa.prune(60, NOW, tmp_path)
        assert not stale_tmp.exists()
        assert not stale_zip.exists()
        assert fresh_tmp.exists()

    def test_missing_directory(self, tmp_path):
        assert pa.prune(60, NOW, tmp_path / "nope") == 0


class TestSummaryClearList:
    def test_missing_and_empty_directory(self, tmp_path):
        for directory in (tmp_path / "nope", tmp_path):
            result = pa.summary({}, directory)
            assert result["count"] == 0
            assert result["total_bytes"] == 0
            assert result["oldest"] is None
            assert result["newest"] is None
            assert result["enabled"] is True
            assert result["retention_days"] == 60

    def test_summary_of_three_files(self, tmp_path):
        times = [NOW - timedelta(days=d) for d in (3, 2, 1)]
        for i, moment in enumerate(times):
            _touch(tmp_path, moment, payload=b"x" * (i + 1))
        result = pa.summary({"debug": {"plan_archive_retention_days": 3}}, tmp_path)
        assert result["count"] == 3
        assert result["total_bytes"] == 6
        assert result["oldest"] == times[0].isoformat()
        assert result["newest"] == times[2].isoformat()
        assert result["retention_days"] == 7

    def test_disabled_flag_reported(self, tmp_path):
        assert pa.summary({"debug": {"plan_archive_enabled": False}}, tmp_path)["enabled"] is False

    def test_clear_only_archive_records(self, tmp_path):
        _touch(tmp_path, NOW)
        _touch(tmp_path, NOW - timedelta(days=1), "err")
        other = tmp_path / "notes.txt"
        other.write_text("keep")
        assert pa.clear(tmp_path) == 2
        assert [f.name for f in tmp_path.iterdir()] == ["notes.txt"]
        assert pa.clear(tmp_path / "nope") == 0

    def test_list_records_days_filter(self, tmp_path):
        _touch(tmp_path, NOW - timedelta(hours=2))
        _touch(tmp_path, NOW - timedelta(days=3), "err")
        recent = pa.list_records(days=1, directory=tmp_path, now=NOW)
        assert [r["outcome"] for r in recent] == ["ok"]
        both = pa.list_records(directory=tmp_path)
        assert [r["outcome"] for r in both] == ["error", "ok"]
        assert both[0]["time"] == NOW - timedelta(days=3)


class TestDownloadZip:
    def test_zip_contains_identical_records_and_manifest(self, tmp_path):
        a = _touch(tmp_path, NOW - timedelta(days=2), payload=b"first")
        b = _touch(tmp_path, NOW, "err", payload=b"second")
        zip_path = pa.build_download_zip(None, tmp_path)
        try:
            with zipfile.ZipFile(zip_path) as bundle:
                assert set(bundle.namelist()) == {a.name, b.name, "manifest.json"}
                assert bundle.read(a.name) == b"first"
                assert bundle.read(b.name) == b"second"
                assert all(i.compress_type == zipfile.ZIP_STORED for i in bundle.infolist())
                manifest = json.loads(bundle.read("manifest.json"))
            assert manifest == [
                {
                    "name": a.name,
                    "time": (NOW - timedelta(days=2)).isoformat(),
                    "outcome": "ok",
                    "size": 5,
                },
                {"name": b.name, "time": NOW.isoformat(), "outcome": "error", "size": 6},
            ]
        finally:
            zip_path.unlink()

    def test_days_filter(self, tmp_path):
        now = datetime.now(UTC).replace(microsecond=0)
        _touch(tmp_path, now - timedelta(days=3))
        recent = _touch(tmp_path, now - timedelta(hours=1))
        zip_path = pa.build_download_zip(1, tmp_path)
        try:
            with zipfile.ZipFile(zip_path) as bundle:
                assert set(bundle.namelist()) == {recent.name, "manifest.json"}
        finally:
            zip_path.unlink()

    def test_empty_archive_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            pa.build_download_zip(None, tmp_path)
        assert list(tmp_path.iterdir()) == []
