"""BenchmarkService storage, idempotence and read-only behaviour, plus the API."""

import json
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from backend.api.routers.energy import get_battery_benchmark
from backend.learning.models import Base, SlotObservation, SystemState
from backend.learning.store import LearningStore
from backend.services import benchmark_service as service_module
from backend.services.benchmark_service import BenchmarkService
from planner.errors import PlannerError, PlannerErrorCode
from tests.backend.test_battery_benchmark import TZ, _day_rows

NOW = TZ.localize(datetime(2026, 10, 11, 0, 10))
YESTERDAY = date(2026, 10, 10)
CONFIG = {
    "timezone": "Europe/Stockholm",
    "system": {
        "battery": {
            "capacity_kwh": 10.0,
            "min_soc_percent": 0.0,
            "max_charge_a": 200.0,
            "max_discharge_a": 200.0,
            "charge_efficiency": 1.0,
            "discharge_efficiency": 1.0,
        }
    },
}


@pytest_asyncio.fixture
async def store(tmp_path):
    value = LearningStore(str(tmp_path / "learning.db"), TZ)
    async with value.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with value.AsyncSession() as session:
        for row in _day_rows(YESTERDAY - timedelta(days=1)) + _day_rows(YESTERDAY):
            session.add(SlotObservation(**row))
        await session.commit()
    yield value
    await value.close()


def _service() -> BenchmarkService:
    return BenchmarkService(config_loader=lambda: CONFIG, now=lambda: NOW)


async def _stored(store: LearningStore) -> dict[str, dict]:
    async with store.AsyncSession() as session:
        rows = (await session.execute(select(SystemState))).scalars().all()
    return {r.key: json.loads(r.value) for r in rows}


@pytest.mark.asyncio
async def test_run_stores_last_14_days_and_restart_does_not_recompute(store):
    processed = await _service().run_once(store)
    assert processed[0] == date(2026, 9, 27) and processed[-1] == YESTERDAY
    assert len(processed) == 14
    stored = await _stored(store)
    assert stored["battery_benchmark:2026-10-10"]["status"] == "scored"
    assert stored["battery_benchmark:2026-10-09"]["reason"] == "incomplete_day"
    assert "battery_benchmark:2026-10-11" not in stored

    with patch("backend.battery_benchmark.KeplerSolver.solve") as solve:
        assert await _service().run_once(store) == []
    solve.assert_not_called()


@pytest.mark.asyncio
async def test_version_bump_recomputes_stored_days(store):
    await _service().run_once(store)
    with patch.object(service_module, "BENCHMARK_VERSION", service_module.BENCHMARK_VERSION + 1):
        assert len(await _service().run_once(store)) == 14


@pytest.mark.asyncio
async def test_v1_capacity_mismatch_record_is_recomputed(store):
    await _service().run_once(store)
    legacy = {"version": 1, "date": YESTERDAY.isoformat(), "status": "excluded", "reason": "capacity_mismatch"}
    await store.set_system_state("battery_benchmark:2026-10-10", json.dumps(legacy))
    assert await _service().run_once(store) == [YESTERDAY]
    record = (await _stored(store))["battery_benchmark:2026-10-10"]
    assert (record["version"], record["status"], record["reason"]) == (2, "scored", None)
    assert record["warnings"] == []


@pytest.mark.asyncio
async def test_failed_solve_is_stored(store):
    error = PlannerError(
        code=PlannerErrorCode.SOLVER_INFEASIBLE, details={"solver_status": "Infeasible"}
    )
    with patch("backend.battery_benchmark.KeplerSolver.solve", side_effect=error):
        await _service().run_once(store)
    record = (await _stored(store))["battery_benchmark:2026-10-10"]
    assert (record["status"], record["solver_status"], record["score"]) == (
        "failed",
        "Infeasible",
        None,
    )
    # Failed days are retried on the next run while inside the window; others are not.
    assert await _service().run_once(store) == [YESTERDAY]
    assert (await _stored(store))["battery_benchmark:2026-10-10"]["status"] == "scored"


@pytest.mark.asyncio
async def test_run_writes_only_benchmark_state(store):
    async with store.AsyncSession() as session:
        before = [r.__dict__.copy() for r in (await session.execute(select(SlotObservation))).scalars()]
    await _service().run_once(store)
    async with store.AsyncSession() as session:
        after = [r.__dict__.copy() for r in (await session.execute(select(SlotObservation))).scalars()]
    strip = lambda rows: [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]  # noqa: E731
    assert strip(before) == strip(after)
    assert all(key.startswith("battery_benchmark:") for key in await _stored(store))


@pytest.mark.asyncio
async def test_api_returns_stored_days_and_totals_without_solving(store):
    await _service().run_once(store)
    with (
        patch("backend.api.routers.energy.load_yaml", return_value=CONFIG),
        patch("backend.battery_benchmark.KeplerSolver.solve") as solve,
    ):
        body = await get_battery_benchmark(
            start_date=date(2026, 10, 9), end_date=YESTERDAY, store=store
        )
    solve.assert_not_called()
    assert [d["date"] for d in body["days"]] == ["2026-10-09", "2026-10-10"]
    assert body["totals"]["days_scored"] == 1
    assert body["totals"]["days_total"] == 2
    assert body["totals"]["missed_sek"] == pytest.approx(body["days"][1]["missed_sek"])


@pytest.mark.asyncio
async def test_api_validates_range(store):
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        with pytest.raises(HTTPException):
            await get_battery_benchmark(
                start_date=YESTERDAY, end_date=YESTERDAY - timedelta(days=1), store=store
            )
        with pytest.raises(HTTPException):
            await get_battery_benchmark(
                start_date=YESTERDAY - timedelta(days=366), end_date=YESTERDAY, store=store
            )
        body = await get_battery_benchmark(end_date=YESTERDAY, store=store)
    assert body["start_date"] == "2026-09-11"
    assert body["days"] == [] and body["totals"]["score"] is None
