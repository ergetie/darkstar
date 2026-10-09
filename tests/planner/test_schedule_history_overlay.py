import json
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
from backend.measurement_provenance import recording_metadata


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


# --- consistency-hardening: real slot duration ---


@pytest.mark.parametrize(
    ("end", "expected"),
    [
        ("2026-09-24T11:00:00+02:00", 1.0),
        ("2026-09-24T10:30:00+02:00", 0.5),
        ("2026-09-24T10:30:00", 0.5),  # naive end takes the start's offset
        (None, 0.25),
        ("garbage", 0.25),
        ("2026-09-24T10:00:00+02:00", 0.25),  # not after start
        ("2026-09-24T09:45:00+02:00", 0.25),
    ],
)
def test_slot_duration_hours(end, expected):
    from backend.api.routers.schedule import _slot_duration_hours

    start = datetime.fromisoformat("2026-09-24T10:00:00+02:00")
    assert _slot_duration_hours(start, end) == pytest.approx(expected)


@pytest.mark.anyio
async def test_history_uses_real_slot_duration(tmp_path):
    db_path = tmp_path / "planner_learning.db"
    tz = pytz.timezone("Europe/Stockholm")
    today_start = tz.localize(datetime.combine(datetime.now(tz).date(), time(0, 0)))
    hour_slot = today_start.replace(hour=1)
    null_slot = today_start.replace(hour=2)
    half_slot = today_start.replace(hour=3)

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            insert_plan = text(
                "INSERT INTO slot_plans (slot_start, slot_end, planned_soc_percent, "
                "planned_water_heating_kwh, planned_ev_charging_kwh) "
                "VALUES (:s, :e, 50.0, :w, :ev)"
            )
            await conn.execute(
                insert_plan,
                {
                    "s": hour_slot.isoformat(),
                    "e": (hour_slot + timedelta(hours=1)).isoformat(),
                    "w": 0.0,
                    "ev": 11.0,
                },
            )
            await conn.execute(
                insert_plan, {"s": null_slot.isoformat(), "e": None, "w": 0.5, "ev": 0.0}
            )
            await conn.execute(
                insert_plan,
                {
                    "s": half_slot.isoformat(),
                    "e": (half_slot + timedelta(minutes=30)).isoformat(),
                    "w": 0.0,
                    "ev": 0.0,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO slot_observations (slot_start, slot_end, water_kwh, quality_flags) "
                    "VALUES (:s, :e, 1.5, :flags)"
                ),
                {
                    "s": half_slot.isoformat(),
                    "e": (half_slot + timedelta(minutes=30)).isoformat(),
                    "flags": json.dumps(
                        {
                            "water_heater_energy": {
                                "schema_version": 1,
                                "semantics": "active-water-energy-v1",
                                "devices": {
                                    "tank": {
                                        "energy_kwh": 0.5,
                                        "source": "power_history",
                                        "idle_power_threshold_kw": 0.0,
                                        "coverage": "complete",
                                    }
                                },
                            }
                        }
                    ),
                },
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
    assert by_start[hour_slot.isoformat()]["ev_charging_kw"] == pytest.approx(11.0)
    assert by_start[null_slot.isoformat()]["water_heating_kw"] == pytest.approx(2.0)
    # Legacy aggregate-only rows without ownership evidence stay unknown.
    assert by_start[half_slot.isoformat()]["actual_water_kw"] is None
    assert by_start[half_slot.isoformat()]["actual_water_heaters_kw"] == {}
    assert by_start[half_slot.isoformat()]["planned_water_heating_kw"] == pytest.approx(0.0)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("now_time", "completed"),
    [(time(18, 56), False), (time(19, 0), True)],
)
async def test_current_water_slot_keeps_plan_until_end_and_then_shows_supported_actual(
    tmp_path, now_time, completed
):
    db_path = tmp_path / "planner_learning.db"
    tz = pytz.timezone("Europe/Stockholm")
    today = datetime.now(tz).date()
    slot_start = tz.localize(datetime.combine(today, time(18, 45)))
    slot_end = slot_start + timedelta(minutes=15)
    config = {
        "system": {"has_water_heater": True},
        "water_heaters": [
            {
                "id": "tank",
                "enabled": True,
                "sensor": "sensor.tank",
                "idle_power_threshold_kw": 0.1,
            },
            {
                "id": "upstairs",
                "enabled": True,
                "sensor": "sensor.upstairs",
                "idle_power_threshold_kw": 0.1,
            },
        ],
    }
    flags = {
        "source": "recorder",
        "recording": recording_metadata(
            config,
            {"water": {"method": "power_history", "owner": "recorder"}},
            "unavailable",
        ),
        "water_heater_energy": {
            "schema_version": 1,
            "semantics": "active-water-energy-v1",
            "devices": {
                "tank": {
                    "energy_kwh": 0.0,
                    "source": "power_history",
                    "idle_power_threshold_kw": 0.1,
                    "coverage": "complete",
                },
                "upstairs": {
                    "energy_kwh": 0.25,
                    "source": "snapshot",
                    "idle_power_threshold_kw": 0.1,
                    "coverage": "complete",
                },
            },
        },
    }
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(
                text(
                    "INSERT INTO slot_plans (slot_start, slot_end, planned_soc_percent, "
                    "planned_water_heating_kwh) VALUES (:s, :e, 50.0, 0.75)"
                ),
                {"s": slot_start.isoformat(), "e": slot_end.isoformat()},
            )
            await conn.execute(
                text(
                    "INSERT INTO slot_observations (slot_start, slot_end, water_kwh, quality_flags) "
                    "VALUES (:s, :e, 0.25, :flags)"
                ),
                {
                    "s": slot_start.isoformat(),
                    "e": slot_end.isoformat(),
                    "flags": json.dumps(flags),
                },
            )
    finally:
        await engine.dispose()

    fixed_now = tz.localize(datetime.combine(today, now_time))
    mock_config = {"learning": {"sqlite_path": str(db_path)}, "timezone": "Europe/Stockholm"}
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
        MockPath.side_effect = lambda _arg: MagicMock(exists=MagicMock(return_value=False))

        store = LearningStore(str(db_path), tz)
        try:
            result = await schedule_today_with_history(store=store)
        finally:
            await store.close()

    slot = next(row for row in result["slots"] if row["start_time"] == slot_start.isoformat())
    assert slot["water_heating_kw"] == pytest.approx(3.0)
    assert slot["planned_water_heating_kw"] == pytest.approx(3.0)
    assert slot["is_completed"] is completed
    assert slot.get("actual_water_kw") == (1.0 if completed else None)
    if completed:
        assert slot["actual_water_available"] is True
        assert slot["actual_water_source"] == "power_history"
        assert slot["actual_water_heaters_kw"] == {"tank": 0.0, "upstairs": 1.0}
        assert slot["actual_water_heater_sources"] == {
            "tank": "power_history",
            "upstairs": "snapshot",
        }
        assert sum(slot["actual_water_heaters_kw"].values()) == pytest.approx(
            slot["actual_water_kw"]
        )


@pytest.mark.anyio
@pytest.mark.parametrize("now_time", [time(18, 56), time(19, 0)])
async def test_live_water_plan_wins_over_stale_database_and_current_telemetry(tmp_path, now_time):
    tz = pytz.timezone("Europe/Stockholm")
    day = datetime.now(tz).date()
    start = tz.localize(datetime.combine(day, time(18, 45)))
    end = start + timedelta(minutes=15)
    live = {
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "water_heating_kw": 3.1,
        "water_heaters": {"tank": {"heating_kw": 3.1}},
        "grid_import_kw": 4.0,
    }
    schedule_file = tmp_path / "schedule.json"
    schedule_file.write_text(json.dumps({"schedule": [live]}))
    store = MagicMock()
    store.get_history_range = AsyncMock(
        return_value=[
            {
                "slot_start": start.isoformat(),
                "slot_end": end.isoformat(),
                "batt_charge_kwh": 0,
                "batt_discharge_kwh": 0,
                "export_kwh": 0,
                "soc_end_percent": 50,
                "ev_charging_kwh": 0,
                "import_price_sek_kwh": 1,
            }
        ]
    )
    store.get_forecasts_range = AsyncMock(return_value=[])
    store.get_plans_range = AsyncMock(
        return_value=[
            {
                "slot_start": start.isoformat(),
                "slot_end": end.isoformat(),
                "planned_charge_kwh": 0,
                "planned_discharge_kwh": 0,
                "planned_water_heating_kwh": 0,
                "planned_soc_percent": 50,
                "projected_soc_percent": 50,
                "planned_ev_charging_kwh": 0,
                "planned_export_kwh": 0,
            }
        ]
    )
    store.get_observations_range = AsyncMock(
        return_value=[
            {
                "slot_start": start.isoformat(),
                "slot_end": end.isoformat(),
                "water_kwh": 0,
                "pv_kwh": None,
                "load_kwh": None,
                "actual_water_available": False,
            }
        ]
    )
    with (
        patch("backend.api.routers.schedule.Path", return_value=schedule_file),
        patch(
            "backend.api.routers.schedule.load_yaml", return_value={"timezone": "Europe/Stockholm"}
        ),
        patch("backend.api.routers.schedule.get_nordpool_data", new=AsyncMock(return_value=[])),
        patch("backend.api.routers.schedule.datetime") as clock,
    ):
        clock.now.return_value = tz.localize(datetime.combine(day, now_time))
        clock.fromisoformat.side_effect = datetime.fromisoformat
        clock.combine.side_effect = datetime.combine
        clock.min = datetime.min
        result = await schedule_today_with_history(store=store)
    slot = result["slots"][0]
    assert slot["water_heating_kw"] == 3.1
    assert slot["planned_water_heating_kw"] == 3.1
    assert slot["water_heaters"] == {"tank": {"heating_kw": 3.1}}
    assert slot["planned_water_heaters"] == slot["water_heaters"]
    assert slot["grid_import_kw"] == 4.0
    assert slot["actual_soc"] == 50
    assert slot["is_historical"] is (now_time == time(19, 0))
    assert slot.get("actual_water_kw") is None
