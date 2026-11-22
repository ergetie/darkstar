"""PlannerService._execute writes one plan archive record per run."""

import gzip
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.services import plan_archive, planner_service as service_module
from backend.services.planner_service import PlannerService
from planner.errors import PlannerError, PlannerErrorCode


@pytest.fixture
def archive_dir(tmp_path, monkeypatch) -> Path:
    directory = tmp_path / "archive"
    monkeypatch.setattr(plan_archive, "ARCHIVE_DIR", directory)
    monkeypatch.setattr(service_module, "load_yaml", lambda path: {"config_version": 2})
    monkeypatch.setenv("DB_PATH", str(tmp_path / "missing.db"))
    return directory


@pytest.fixture
def service() -> PlannerService:
    svc = PlannerService()
    svc._emit_progress = AsyncMock()
    svc._notify_error = AsyncMock()
    svc._notify_success = AsyncMock()
    svc._count_schedule_slots = lambda: 3
    return svc


def _records(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.json.gz")) if directory.exists() else []


def _load(path: Path) -> dict:
    return json.loads(gzip.decompress(path.read_bytes()))


async def test_success_run_writes_ok_record(service, archive_dir):
    async def run_planner(**kwargs):
        plan_archive.capture("inputs", {"price_data": [1]})
        plan_archive.capture("schedule", {"schedule": [], "meta": {}})
        return 0

    with patch("bin.run_planner.main", side_effect=run_planner):
        result = await service.run_once()

    assert result.success is True
    (path,) = _records(archive_dir)
    assert path.name.endswith("-ok.json.gz")
    record = _load(path)
    assert record["outcome"] == "ok"
    assert record["inputs"] == {"price_data": [1]}
    assert record["config_version"] == 2


async def test_planner_error_writes_err_record_with_earlier_inputs(service, archive_dir):
    async def run_planner(**kwargs):
        plan_archive.capture("inputs", {"price_data": [1]})
        raise PlannerError(PlannerErrorCode.SOLVER_INFEASIBLE, details={"slots": 4})

    with patch("bin.run_planner.main", side_effect=run_planner):
        result = await service.run_once()

    assert result.error_code == "SOLVER_INFEASIBLE"
    (path,) = _records(archive_dir)
    assert path.name.endswith("-err.json.gz")
    record = _load(path)
    assert record["outcome"] == "error"
    assert record["error"]["code"] == "SOLVER_INFEASIBLE"
    assert record["error"]["details"] == {"slots": 4}
    assert record["error"]["message"]
    assert record["inputs"] == {"price_data": [1]}


async def test_input_fetch_exception_writes_err_record_without_inputs(service, archive_dir):
    async def run_planner(**kwargs):
        raise RuntimeError("fetch exploded")

    with patch("bin.run_planner.main", side_effect=run_planner):
        result = await service.run_once()

    assert result.error_code == PlannerErrorCode.UNKNOWN.value
    (path,) = _records(archive_dir)
    record = _load(path)
    assert record["outcome"] == "error"
    assert record["inputs"] == {}
    assert record["error"]["code"] == "UNKNOWN"
    assert "fetch exploded" in record["error"]["message"]


async def test_nonzero_exit_code_is_archived_as_error(service, archive_dir):
    async def run_planner(**kwargs):
        plan_archive.capture("inputs", {"x": 1})
        return 2

    with patch("bin.run_planner.main", side_effect=run_planner):
        result = await service.run_once()

    assert result.success is False
    (path,) = _records(archive_dir)
    assert _load(path)["error"]["message"] == "Planner exited with code 2"


async def test_run_that_planned_nothing_is_not_archived(service, archive_dir):
    async def run_planner(**kwargs):
        return 0  # scheduler disabled: nothing captured

    with patch("bin.run_planner.main", side_effect=run_planner):
        result = await service.run_once()

    assert result.success is True
    assert _records(archive_dir) == []


async def test_disabled_archive_writes_nothing(service, archive_dir, monkeypatch):
    monkeypatch.setattr(
        service_module, "load_yaml", lambda path: {"debug": {"plan_archive_enabled": False}}
    )

    async def run_planner(**kwargs):
        plan_archive.capture("inputs", {"x": 1})
        return 0

    with patch("bin.run_planner.main", side_effect=run_planner):
        await service.run_once()

    assert not archive_dir.exists()


async def test_write_record_raising_does_not_change_result(service, archive_dir):
    async def run_planner(**kwargs):
        plan_archive.capture("inputs", {"x": 1})
        return 0

    with (
        patch("bin.run_planner.main", side_effect=run_planner),
        patch.object(plan_archive, "write_record", side_effect=RuntimeError("archive broke")),
    ):
        result = await service.run_once()

    assert result.success is True
    assert result.slot_count == 3
    assert result.error is None
    assert service._consecutive_failures == 0


async def test_capture_does_not_leak_after_run(service, archive_dir):
    async def run_planner(**kwargs):
        return 0

    with patch("bin.run_planner.main", side_effect=run_planner):
        await service.run_once()

    plan_archive.capture("leak", True)  # no capture active: must be a no-op
    assert plan_archive._current.get() is None
