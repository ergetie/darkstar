import importlib.util
import sqlite3
from pathlib import Path


def _load_backfill_ha_module():
    module_path = Path("bin/backfill_ha.py")
    spec = importlib.util.spec_from_file_location("backfill_ha", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backfill_ha_updates_base_load_by_subtracting_deferrable_loads():
    backfill_ha = _load_backfill_ha_module()

    with sqlite3.connect(":memory:") as conn:
        conn.execute(
            """
            CREATE TABLE slot_observations (
                slot_start TEXT PRIMARY KEY,
                load_kwh REAL,
                pv_kwh REAL,
                import_kwh REAL,
                export_kwh REAL,
                batt_charge_kwh REAL,
                batt_discharge_kwh REAL,
                ev_charging_kwh REAL,
                water_kwh REAL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO slot_observations (
                slot_start, load_kwh, pv_kwh, import_kwh, export_kwh,
                batt_charge_kwh, batt_discharge_kwh, ev_charging_kwh, water_kwh
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2026-06-16T10:30:00+02:00", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.30, 0.20),
        )

        backfill_ha.update_slot_observations(
            conn,
            [(1.25, 0.45, 0.10, 0.00, 0.00, 0.00, "2026-06-16T10:30:00+02:00")],
        )

        row = conn.execute(
            """
            SELECT load_kwh, pv_kwh, import_kwh, export_kwh,
                   batt_charge_kwh, batt_discharge_kwh
            FROM slot_observations
            """
        ).fetchone()

    assert row == (0.75, 0.45, 0.10, 0.00, 0.00, 0.00)


def test_backfill_ha_clamps_negative_base_load_to_zero():
    backfill_ha = _load_backfill_ha_module()

    with sqlite3.connect(":memory:") as conn:
        conn.execute(
            """
            CREATE TABLE slot_observations (
                slot_start TEXT PRIMARY KEY,
                load_kwh REAL,
                pv_kwh REAL,
                import_kwh REAL,
                export_kwh REAL,
                batt_charge_kwh REAL,
                batt_discharge_kwh REAL,
                ev_charging_kwh REAL,
                water_kwh REAL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO slot_observations (
                slot_start, load_kwh, pv_kwh, import_kwh, export_kwh,
                batt_charge_kwh, batt_discharge_kwh, ev_charging_kwh, water_kwh
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2026-06-16T10:45:00+02:00", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.80, 0.20),
        )

        backfill_ha.update_slot_observations(
            conn,
            [(0.50, 0.10, 0.00, 0.00, 0.00, 0.00, "2026-06-16T10:45:00+02:00")],
        )

        load_kwh = conn.execute("SELECT load_kwh FROM slot_observations").fetchone()[0]

    assert load_kwh == 0.0
