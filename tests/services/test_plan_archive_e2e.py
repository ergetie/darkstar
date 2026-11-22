"""End to end: a real planner run through PlannerService is archived, downloaded and cleared."""

import gzip
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routers import debug as debug_router
from backend.services import plan_archive
from backend.services.planner_service import PlannerService
from tests.planner.test_price_reserve_pipeline import make_full_inputs, reserve_config

FORMAT_KEYS = {
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


async def test_run_archive_download_clear(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    archive_dir = tmp_path / "data" / "plan_archive"
    monkeypatch.setattr(plan_archive, "ARCHIVE_DIR", archive_dir)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "missing.db"))

    config = reserve_config(tmp_path / "learning.db", enabled=False)
    config["automation"] = {"enable_scheduler": True}
    config["config_version"] = 2
    config["home_assistant"] = {"token": "SECRET-TOKEN-XYZ"}
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(config))

    start = (datetime.now(UTC) - timedelta(minutes=20)).replace(second=0, microsecond=0)
    start = start.replace(minute=start.minute - start.minute % 15)
    inputs = make_full_inputs(start)

    async def fake_inputs(*args, **kwargs):
        return inputs

    service = PlannerService()
    service._emit_progress = AsyncMock()
    service._notify_error = AsyncMock()
    service._notify_success = AsyncMock()
    monkeypatch.setattr("backend.services.planner_service.load_yaml", lambda path: config)

    with patch("bin.run_planner.get_all_input_data", side_effect=fake_inputs):
        result = await service.run_once()

    assert result.success is True, result.error
    (record_path,) = sorted(archive_dir.glob("*.json.gz"))
    assert record_path.name.endswith("-ok.json.gz")
    raw = gzip.decompress(record_path.read_bytes())
    record = json.loads(raw)
    assert set(record) == FORMAT_KEYS
    assert record["format_version"] == 1
    assert record["outcome"] == "ok"
    assert record["config_version"] == 2
    assert b"SECRET-TOKEN-XYZ" not in raw
    assert len(record["inputs"]["price_data"]) == len(inputs["price_data"])
    assert record["schedule"] == json.loads((tmp_path / "data" / "schedule.json").read_text())
    assert record["solver_status"]
    assert record["initial_soc_kwh"] > 0

    monkeypatch.setattr(debug_router, "load_yaml", lambda path: config)
    app = FastAPI()
    app.include_router(debug_router.router)
    client = TestClient(app)

    summary = client.get("/api/debug/plan-archive").json()
    assert summary["count"] == 1

    download = client.get("/api/debug/plan-archive/download")
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.content)) as bundle:
        assert bundle.read(record_path.name) == record_path.read_bytes()

    assert client.delete("/api/debug/plan-archive").json() == {"deleted": 1}
    assert list(archive_dir.glob("*.json.gz")) == []
