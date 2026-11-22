"""Pipeline capture points for the plan archive."""

import json
from pathlib import Path

import pytest

from backend.services import plan_archive
from planner.pipeline import PlannerPipeline
from tests.planner.test_price_reserve_pipeline import (
    TZ,
    future_base,
    make_full_inputs,
    reserve_config,
)

CAPTURE_KEYS = {
    "initial_soc_kwh",
    "initial_soc_percent",
    "safety_floor",
    "solver_status",
    "time_limit_hit",
    "schedule",
}


async def _run(tmp_path: Path):
    start = future_base()
    pipeline = PlannerPipeline(reserve_config(tmp_path / "learning.db", enabled=False))
    return await pipeline.generate_schedule(
        make_full_inputs(start),
        mode="full",
        save_to_file=True,
        now_override=start.astimezone(TZ),
    )


@pytest.mark.asyncio
async def test_active_capture_receives_all_keys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run = plan_archive.start_capture()
    try:
        await _run(tmp_path)
    finally:
        plan_archive.end_capture()

    assert set(run.data) >= CAPTURE_KEYS
    # Battery capacity 27 kWh, initial state 20 %.
    assert run.data["initial_soc_kwh"] == pytest.approx(run.data["initial_soc_percent"] * 0.27)
    assert run.data["initial_soc_percent"] == pytest.approx(20.0)
    assert {"target_soc_kwh", "target_soc_pct"} <= set(run.data["safety_floor"])
    assert isinstance(run.data["solver_status"], str)
    assert run.data["time_limit_hit"] in (True, False)
    written = json.loads(Path("data/schedule.json").read_text())
    archived = json.loads(json.dumps(run.data["schedule"], default=plan_archive._json_default))
    assert archived == written


@pytest.mark.asyncio
async def test_without_capture_runs_without_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    df = await _run(tmp_path)
    assert not df.empty
