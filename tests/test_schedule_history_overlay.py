from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import aiosqlite
import pytest
import pytz

from backend.api.routers.schedule import schedule_today_with_history


@pytest.mark.anyio
async def test_today_with_history_includes_planned_actions(tmp_path):
    # Setup temp DB
    db_path = tmp_path / "planner_learning.db"

    # Create the slots_forecasts and slot_observations tables too because the code queries them
    # and might fail or warn if missing (though the try/except blocks should handle it).
    # But slot_plans is what we care about.

    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("""
            CREATE TABLE slot_plans (
                slot_start TEXT PRIMARY KEY,
                planned_charge_kwh REAL,
                planned_discharge_kwh REAL,
                planned_soc_percent REAL,
                planned_export_kwh REAL,
                planned_water_heating_kwh REAL
            )
        """)
        await conn.execute("""
             CREATE TABLE slot_observations (
                slot_start TEXT PRIMARY KEY,
                slot_end TEXT,
                batt_charge_kwh REAL,
                batt_discharge_kwh REAL,
                soc_end_percent REAL,
                water_kwh REAL,
                import_kwh REAL,
                export_kwh REAL,
                import_price_sek_kwh REAL
            )
        """)
        await conn.execute("""
             CREATE TABLE slot_forecasts (
                slot_start TEXT PRIMARY KEY,
                pv_forecast_kwh REAL,
                load_forecast_kwh REAL,
                forecast_version TEXT
            )
        """)

        # Insert test data for today (UTC to avoid timezone confusion in test)
        # Using UTC as the configured timezone
        tz = pytz.UTC
        now = datetime.now(tz)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # 1. Planned Charge Slot at 10:00
        slot_10 = today_start.replace(hour=10).isoformat()
        await conn.execute(
            """
            INSERT INTO slot_plans (slot_start, planned_charge_kwh, planned_discharge_kwh, planned_soc_percent, planned_export_kwh, planned_water_heating_kwh)
            VALUES (?, 0.5, 0.0, 50.0, 0.0, 0.25)
        """,
            (slot_10,),
        )

        # 2. Planned Discharge Slot at 11:00
        slot_11 = today_start.replace(hour=11).isoformat()
        await conn.execute(
            """
            INSERT INTO slot_plans (slot_start, planned_charge_kwh, planned_discharge_kwh, planned_soc_percent, planned_export_kwh, planned_water_heating_kwh)
            VALUES (?, 0.0, 0.25, 40.0, 0.1, 0.0)
        """,
            (slot_11,),
        )

        await conn.commit()

    # Mock config to point to temp DB
    mock_config = {"learning": {"sqlite_path": str(db_path)}, "timezone": "UTC"}

    # Patch load_yaml to return our mock config
    with patch("backend.api.routers.schedule.load_yaml", return_value=mock_config):
        # Patch Path to hide schedule.json so we rely on DB + Plans
        # We need to preserve behavior for db_path so aiosqlite can open it
        real_Path = Path
        with patch("backend.api.routers.schedule.Path") as MockPath:

            def side_effect(arg):
                if str(arg) == "schedule.json":
                    m = MagicMock()
                    m.exists.return_value = False
                    return m
                return real_Path(arg)

            MockPath.side_effect = side_effect

            result = await schedule_today_with_history()

    # Assertions
    slots = result["slots"]
    print(f"DEBUG: Returned {len(slots)} slots")
    for s in slots:
        print(f"DEBUG SLOT: {s}")

    assert len(slots) > 0

    # We expect synthetic slots to be created if schedule.json is empty
    # The code does: "all_keys = sorted(set(schedule_map.keys()) | set(exec_map.keys()) | set(planned_map.keys()))"
    # So we should at least have the slots we put in slot_plans.

    found_charge = False
    found_discharge = False

    for slot in slots:
        # Times in response are ISO strings
        if "10:00:00" in slot["start_time"]:
            # 0.5 kWh / 0.25h = 2.0 kW
            # 0.25 kWh / 0.25h = 1.0 kW (Water)
            print(f"Checking slot 10:00: {slot}")
            if (
                slot.get("battery_charge_kw") == 2.0
                and slot.get("soc_target_percent") == 50.0
                and slot.get("water_heating_kw") == 1.0
            ):
                found_charge = True

        if "11:00:00" in slot["start_time"]:
            # 0.25 kWh / 0.25h = 1.0 kW
            print(f"Checking slot 11:00: {slot}")
            if slot.get("battery_discharge_kw") == 1.0 and slot.get("export_kwh") == 0.1:
                found_discharge = True

    assert found_charge, (
        "Did not find planned charge/water slot from DB (expected 2.0 kW charge, 1.0 kW water)"
    )
    assert found_discharge, (
        "Did not find planned discharge slot from DB (expected 1.0 kW discharge)"
    )

@pytest.mark.anyio
async def test_today_with_history_sets_executed_flag(tmp_path):
    """Verify that historical slots from observations have is_executed=True."""
    db_path = tmp_path / "planner_learning.db"
    
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("""
            CREATE TABLE slot_observations (
                slot_start TEXT PRIMARY KEY,
                slot_end TEXT,
                batt_charge_kwh REAL,
                batt_discharge_kwh REAL,
                soc_end_percent REAL,
                water_kwh REAL,
                import_kwh REAL,
                export_kwh REAL,
                import_price_sek_kwh REAL
            )
        """)
        await conn.execute("""
            CREATE TABLE slot_forecasts (
                slot_start TEXT PRIMARY KEY,
                pv_forecast_kwh REAL,
                load_forecast_kwh REAL,
                forecast_version TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE slot_plans (
                slot_start TEXT PRIMARY KEY,
                planned_charge_kwh REAL,
                planned_discharge_kwh REAL,
                planned_soc_percent REAL,
                planned_export_kwh REAL,
                planned_water_heating_kwh REAL
            )
        """)

        # Insert historical observation for "now - 1 hour"
        tz = pytz.UTC
        now = datetime.now(tz)
        past_start = (now - timedelta(minutes=60)).replace(minute=0, second=0, microsecond=0)
        past_end = past_start + timedelta(minutes=15)
        
        await conn.execute(
            "INSERT INTO slot_observations (slot_start, slot_end, batt_charge_kwh, batt_discharge_kwh, soc_end_percent, water_kwh, import_kwh, export_kwh, import_price_sek_kwh) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (past_start.isoformat(), past_end.isoformat(), 0.5, 0.0, 50.0, 0.0, 0.0, 0.0, 0.5)
        )
        await conn.commit()

    # Mock config
    mock_config = {"learning": {"sqlite_path": str(db_path)}, "timezone": "UTC"}

    from unittest.mock import patch, MagicMock

    with patch("backend.api.routers.schedule.load_yaml", return_value=mock_config):
        with patch("backend.api.routers.schedule.Path") as MockPath:
             # Hide schedule.json so we rely on DB
            def side_effect(arg):
                if str(arg) == "schedule.json":
                    m = MagicMock()
                    m.exists.return_value = False
                    return m
                return Path(arg) # Use real path for DB

            MockPath.side_effect = side_effect
            
            from backend.api.routers.schedule import schedule_today_with_history
            result = await schedule_today_with_history()

    slots = result["slots"]
    found_executed = False
    
    target_time_str = past_start.isoformat()
    
    for slot in slots:
        if slot["start_time"] == target_time_str:
            print(f"Checking slot {target_time_str}: {slot}")
            if slot.get("is_executed") is True:
                found_executed = True
                # Also verify mapping of actual_charge_kw (0.5 kWh / 0.25h = 2.0 kW)
                assert slot.get("actual_charge_kw") == 2.0
            
    assert found_executed, "Did not find is_executed=True for historical slot"
