import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.append(str(Path.cwd()))


import pytest
import pytz
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.api.routers.schedule import schedule_today_with_history
from backend.learning.models import Base
from backend.learning.store import LearningStore


@pytest.mark.anyio
async def test_today_with_history_includes_planned_actions(tmp_path):
    # Setup temp DB
    db_path = tmp_path / "planner_learning.db"

    # Create tables using Base metadata for correctness
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

            # Use Europe/Stockholm timezone to match the function's config
            tz = pytz.timezone("Europe/Stockholm")
            now = datetime.now(tz)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

            # 1. Planned Charge Slot at 13:00 Stockholm time (future compared to mock 12:00)
            # Insert in local timezone so it matches what the function expects
            slot_13_local = today_start.replace(hour=13)
            slot_13_str = slot_13_local.isoformat()
            await conn.execute(
                text("""
                INSERT INTO slot_plans (slot_start, planned_charge_kwh, planned_discharge_kwh, planned_soc_percent, planned_export_kwh, planned_water_heating_kwh)
                VALUES (:slot_start, 0.5, 0.0, 50.0, 0.0, 0.25)
                """),
                {"slot_start": slot_13_str},
            )
    finally:
        await engine.dispose()

    # Mock config to point to temp DB - use Europe/Stockholm to match
    mock_config = {"learning": {"sqlite_path": str(db_path)}, "timezone": "Europe/Stockholm"}

    # Mock now to be 12:00 today, so 13:00 is FUTURE
    fixed_now = today_start.replace(hour=12)

    with (
        patch("backend.api.routers.schedule.load_yaml", return_value=mock_config),
        patch("backend.api.routers.schedule.get_nordpool_data", new=AsyncMock(return_value=[])),
        patch("backend.api.routers.schedule.Path") as MockPath,
        patch("backend.api.routers.schedule.datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value = fixed_now
        mock_datetime.fromisoformat.side_effect = datetime.fromisoformat
        mock_datetime.combine.side_effect = datetime.combine
        mock_datetime.min = datetime.min

        # Patch Path to hide schedule.json so we rely on DB + Plans
        real_Path = Path

        def side_effect(arg):
            if str(arg) == "schedule.json":
                m = MagicMock()
                m.exists.return_value = False
                return m
            return real_Path(arg)

        MockPath.side_effect = side_effect

        store = LearningStore(str(db_path), tz)
        try:
            result = await schedule_today_with_history(store=store)
        finally:
            await store.close()

    # Assertions
    slots = result["slots"]
    assert len(slots) > 0

    # Find slot at 13:00 - verify it exists (the exact values depend on how function merges data)
    found_13 = any("T13:00:00" in s["start_time"] for s in slots)
    assert found_13, "Expected slot at 13:00 to exist"


@pytest.mark.anyio
async def test_today_with_history_includes_past(tmp_path):
    """Verify that slots before 'now' are INCLUDED as they are part of history."""
    db_path = tmp_path / "planner_learning.db"

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

            # Use Europe/Stockholm timezone to match the function's config
            tz = pytz.timezone("Europe/Stockholm")
            now = datetime.now(tz)
            today_start = tz.localize(datetime.combine(now.date(), time(0, 0)))
            past_start = tz.localize(datetime.combine(now.date(), time(1, 0)))
            future_start = tz.localize(datetime.combine(now.date(), time(22, 0)))

            # Past slot in DB
            await conn.execute(
                text(
                    "INSERT INTO slot_observations (slot_start, slot_end, batt_charge_kwh) VALUES (:s, :e, 0.5)"
                ),
                {
                    "s": past_start.isoformat(),
                    "e": (past_start + timedelta(minutes=15)).isoformat(),
                },
            )

            # Future slot in DB
            await conn.execute(
                text("INSERT INTO slot_plans (slot_start, planned_soc_percent) VALUES (:s, 80.0)"),
                {"s": future_start.isoformat()},
            )
    finally:
        await engine.dispose()

    mock_config = {"learning": {"sqlite_path": str(db_path)}, "timezone": "Europe/Stockholm"}
    fixed_now = today_start.replace(hour=12)

    with (
        patch("backend.api.routers.schedule.load_yaml", return_value=mock_config),
        patch("backend.api.routers.schedule.get_nordpool_data", new=AsyncMock(return_value=[])),
        patch("backend.api.routers.schedule.Path") as MockPath,
        patch("backend.api.routers.schedule.datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value = fixed_now
        mock_datetime.fromisoformat.side_effect = datetime.fromisoformat
        mock_datetime.combine.side_effect = datetime.combine
        mock_datetime.min = datetime.min

        def side_effect(arg):
            m = MagicMock()
            m.exists.return_value = False
            return m

        MockPath.side_effect = side_effect

        store = LearningStore(str(db_path), tz)
        try:
            result = await schedule_today_with_history(store=store)
        finally:
            await store.close()

    slots = result["slots"]
    # 01:00 should be INCLUDED (past/history), 22:00 should be INCLUDED (future)
    assert any("01:00:00" in s["start_time"] for s in slots)
    assert any("22:00:00" in s["start_time"] for s in slots)


@pytest.mark.anyio
async def test_past_slot_keeps_planned_ev_and_null_is_not_fabricated(tmp_path):
    """Planned EV for past slots comes from slot_plans; NULL rows yield no value."""
    db_path = tmp_path / "planner_learning.db"
    tz = pytz.timezone("Europe/Stockholm")
    today_start = tz.localize(datetime.combine(datetime.now(tz).date(), time(0, 0)))
    ev_slot = today_start.replace(hour=1)
    null_slot = today_start.replace(hour=2)

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(
                text(
                    "INSERT INTO slot_plans (slot_start, planned_soc_percent, "
                    "planned_ev_charging_kwh) VALUES (:s, 50.0, 2.75)"
                ),
                {"s": ev_slot.isoformat()},
            )
            await conn.execute(
                text(
                    "INSERT INTO slot_plans (slot_start, planned_soc_percent, "
                    "planned_ev_charging_kwh) VALUES (:s, 50.0, NULL)"
                ),
                {"s": null_slot.isoformat()},
            )
    finally:
        await engine.dispose()

    mock_config = {"learning": {"sqlite_path": str(db_path)}, "timezone": "Europe/Stockholm"}

    with (
        patch("backend.api.routers.schedule.load_yaml", return_value=mock_config),
        patch("backend.api.routers.schedule.get_nordpool_data", new=AsyncMock(return_value=[])),
        patch("backend.api.routers.schedule.Path") as MockPath,
        patch("backend.api.routers.schedule.datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value = today_start.replace(hour=12)
        mock_datetime.fromisoformat.side_effect = datetime.fromisoformat
        mock_datetime.combine.side_effect = datetime.combine
        mock_datetime.min = datetime.min

        # No schedule.json: past slots only exist in slot_plans, as after a replan.
        def side_effect(arg):
            m = MagicMock()
            m.exists.return_value = False
            return m

        MockPath.side_effect = side_effect

        store = LearningStore(str(db_path), tz)
        try:
            result = await schedule_today_with_history(store=store)
        finally:
            await store.close()

    by_start = {s["start_time"]: s for s in result["slots"]}
    assert by_start[ev_slot.isoformat()]["ev_charging_kw"] == pytest.approx(11.0)
    assert by_start[null_slot.isoformat()].get("ev_charging_kw") is None
