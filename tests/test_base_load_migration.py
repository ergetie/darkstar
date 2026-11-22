"""One-time historical flagging of untrusted base loads (idempotent, date-free, no schema change)."""

import json
import logging
import sqlite3
from contextlib import ExitStack
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine

from backend.learning.base_load_migration import STATE_KEY, flag_historical_base_load
from backend.learning.models import Base

CONFIG = {"water_heaters": [{"id": "tank", "sensor": "sensor.wh", "enabled": True}]}
NO_SENSOR_CONFIG = {"water_heaters": [{"id": "tank", "enabled": True}]}


def recording(water_method: str = "power_history") -> dict:
    return {
        "schema_version": 1,
        "semantics": "slot-energy-v1",
        "boundary_fingerprint": "a" * 64,
        "components": {"water": {"method": water_method, "owner": "recorder"}},
        "soc": {"source": "live", "owner": "recorder"},
    }


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "learning.db")
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    return path


def slot(minutes: int, offset: str = "+01:00") -> str:
    return (datetime(2026, 11, 1, 0, 0) + timedelta(minutes=minutes)).isoformat() + offset


def put(db, start, load, water, flags):
    raw = flags if isinstance(flags, str) or flags is None else json.dumps(flags)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO slot_observations (slot_start, slot_end, load_kwh, water_kwh, quality_flags) "
            "VALUES (?, ?, ?, ?, ?)",
            (start, start, load, water, raw),
        )


def flags_of(db, start):
    with sqlite3.connect(db) as conn:
        raw = conn.execute(
            "SELECT quality_flags FROM slot_observations WHERE slot_start = ?", (start,)
        ).fetchone()[0]
    return None if raw is None else json.loads(raw)


def dump(db) -> list[tuple]:
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT * FROM slot_observations ORDER BY slot_start").fetchall()


def reasons(db, start) -> list[str] | None:
    flags = flags_of(db, start) or {}
    base = flags.get("base_load")
    return None if base is None else base["reasons"]


def test_old_clamp_row_and_following_slot(db, caplog):
    put(db, slot(0), 0.0, 0.75, {"source": "recorder"})
    put(db, slot(15), 1.9, 0.0, {"source": "recorder"})
    put(db, slot(30), 0.4, 0.0, {"source": "recorder"})
    with caplog.at_level(logging.INFO):
        counts = flag_historical_base_load(db, {})
    assert counts == {"a": 1, "after_clamp": 1, "b": 0, "skipped_unparseable": 0}
    assert reasons(db, slot(0)) == ["legacy_counter_clamp"]
    assert reasons(db, slot(15)) == ["legacy_counter_after_clamp"]
    assert reasons(db, slot(30)) is None
    assert flags_of(db, slot(0))["base_load"]["reliable"] is False
    assert flags_of(db, slot(0))["source"] == "recorder"
    assert any("a=1 after_clamp=1 b=0" in r.message for r in caplog.records)


def test_row_with_recording_provenance_is_untouched_by_rule_a(db):
    put(db, slot(0), 0.0, 0.75, {"source": "recorder", "recording": recording()})
    flag_historical_base_load(db, {})
    assert reasons(db, slot(0)) is None


def test_no_date_logic_for_late_upgraded_installations(db):
    # Old-recorder rows can be recent: only the missing `recording` key decides.
    start = "2026-12-24T10:00:00+01:00"
    put(db, start, 0.0, 0.5, {"source": "recorder"})
    flag_historical_base_load(db, {})
    assert reasons(db, start) == ["legacy_counter_clamp"]


def test_following_slot_is_found_across_mixed_utc_offsets(db):
    put(db, "2026-10-25T01:45:00+02:00", 0.0, 0.5, None)
    put(db, "2026-10-25T02:00:00+01:00", 0.3, 0.0, None)  # 01:00Z: an hour later, not 15 minutes
    put(db, "2026-10-25T00:00:00+00:00", 0.3, 0.0, None)  # 00:00Z: 15 minutes after 23:45Z
    flag_historical_base_load(db, {})
    assert reasons(db, "2026-10-25T01:45:00+02:00") == ["legacy_counter_clamp"]
    assert reasons(db, "2026-10-25T00:00:00+00:00") == ["legacy_counter_after_clamp"]
    assert reasons(db, "2026-10-25T02:00:00+01:00") is None


def test_disabled_but_configured(db):
    put(db, slot(0), 0.5, 0.0, {"recording": recording("disabled_zero"), "source": "recorder"})
    put(db, slot(15), 0.5, 0.0, {"recording": recording("power_history")})
    counts = flag_historical_base_load(db, CONFIG)
    assert counts is not None
    assert counts["b"] == 1
    assert reasons(db, slot(0)) == ["device_disabled_but_configured"]
    assert reasons(db, slot(15)) is None


def test_no_configured_sensor_flags_nothing_for_rule_b(db):
    put(db, slot(0), 0.5, 0.0, {"recording": recording("disabled_zero")})
    counts = flag_historical_base_load(db, NO_SENSOR_CONFIG)
    assert counts is not None
    assert counts["b"] == 0
    assert reasons(db, slot(0)) is None


def test_rules_combine_and_existing_flags_are_preserved(db):
    existing = {
        "source": "recorder",
        "water_heater_energy": {"schema_version": 1, "devices": {}},
        "base_load": {"reliable": False, "reasons": ["device_partial_coverage"]},
        "recording": recording("disabled_zero"),
    }
    put(db, slot(0), 0.5, 0.0, existing)
    flag_historical_base_load(db, CONFIG)
    flags = flags_of(db, slot(0))
    assert flags["base_load"]["reasons"] == [
        "device_disabled_but_configured",
        "device_partial_coverage",
    ]
    for key in ("source", "water_heater_energy", "recording"):
        assert flags[key] == existing[key]


def test_null_and_malformed_flags(db, caplog):
    put(db, slot(0), 0.0, 0.5, None)
    put(db, slot(15), 0.0, 0.5, "{not json")
    put(db, slot(30), 0.0, 0.5, "[1]")
    with caplog.at_level(logging.WARNING):
        counts = flag_historical_base_load(db, {})
    assert counts is not None
    assert counts["skipped_unparseable"] == 2
    assert flags_of(db, slot(0)) == {
        "base_load": {"reliable": False, "reasons": ["legacy_counter_clamp"], "source": "migration"}
    }
    with sqlite3.connect(db) as conn:
        raw = dict(conn.execute("SELECT slot_start, quality_flags FROM slot_observations"))
    assert raw[slot(15)] == "{not json"
    assert raw[slot(30)] == "[1]"
    assert sum("Skipping row" in r.message for r in caplog.records) == 2


def test_columns_are_never_changed_and_migration_is_idempotent(db):
    put(db, slot(0), 0.0, 0.75, {"source": "recorder"})
    put(db, slot(15), 1.9, 0.0, {"source": "recorder", "recording": recording("disabled_zero")})
    put(db, slot(30), 0.4, 0.0, None)
    before = dump(db)
    flag_historical_base_load(db, CONFIG)
    after_first = dump(db)
    assert [row[:4] for row in after_first] == [row[:4] for row in before]
    # Run the rules again against a fresh state: nothing is added or changed.
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM system_state WHERE key = ?", (STATE_KEY,))
    counts = flag_historical_base_load(db, CONFIG)
    assert dump(db) == after_first
    assert counts is not None
    assert (counts["a"], counts["after_clamp"], counts["b"]) == (0, 0, 0)


def test_runs_once_per_state_key(db):
    put(db, slot(0), 0.0, 0.75, {"source": "recorder"})
    assert flag_historical_base_load(db, {}) is not None
    with sqlite3.connect(db) as conn:
        value = conn.execute("SELECT value FROM system_state WHERE key = ?", (STATE_KEY,)).fetchone()
    assert json.loads(value[0])["a"] == 1
    put(db, slot(60), 0.0, 0.75, {"source": "recorder"})
    assert flag_historical_base_load(db, {}) is None
    assert reasons(db, slot(60)) is None


def test_failure_rolls_back_and_leaves_the_state_key_unset(db):
    put(db, slot(0), 0.0, 0.75, {"source": "recorder"})
    with (
        patch("backend.learning.base_load_migration.json.dumps", side_effect=RuntimeError("boom")),
        pytest.raises(RuntimeError),
    ):
        flag_historical_base_load(db, {})
    assert reasons(db, slot(0)) is None
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT 1 FROM system_state WHERE key = ?", (STATE_KEY,)).fetchone() is None


def test_migrated_rows_are_excluded_by_training_and_demand_consumers(db):
    from backend.grid_only_comparison import GridOnlyObservation, build_grid_only_comparison
    from ml.load_clean import has_unmeasured_device

    start = slot(0)
    put(db, start, 0.0, 0.75, {"source": "recorder"})
    flag_historical_base_load(db, {})
    raw = json.dumps(flags_of(db, start))
    assert has_unmeasured_device(raw)

    import pytz

    when = datetime(2026, 10, 5, tzinfo=pytz.UTC)
    result = build_grid_only_comparison(
        [
            GridOnlyObservation(
                start=when,
                import_kwh=1.0,
                export_kwh=0.0,
                import_price_sek_kwh=2.0,
                export_price_sek_kwh=1.0,
                load_kwh=0.0,
                water_kwh=0.75,
                ev_charging_kwh=0.0,
                quality_flags=flags_of(db, start),
            )
        ],
        [when],
        timezone=pytz.UTC,
        hourly=True,
        axis_start=when,
        axis_end=when + timedelta(minutes=15),
        has_completed_observations=True,
        battery_present=False,
        cycle_cost_kwh=0.0,
    )
    assert result["status"] == "unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_startup_runs_the_migration_fail_open(tmp_path, monkeypatch, fails):
    from backend.main import lifespan

    db_path = tmp_path / "planner_learning.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    executor = MagicMock()
    executor.config.enabled = False
    migration = MagicMock(side_effect=RuntimeError("boom") if fails else None)
    with ExitStack() as stack:
        for p in (
            patch("ml.bootstrap.ensure_active_models"),
            patch("backend.main.load_yaml", return_value={"timezone": "UTC"}),
            patch("backend.services.scheduler_service.scheduler_service.start", new_callable=AsyncMock),
            patch("backend.services.scheduler_service.scheduler_service.stop", new_callable=AsyncMock),
            patch("backend.services.recorder_service.recorder_service.start", new_callable=AsyncMock),
            patch("backend.services.recorder_service.recorder_service.stop", new_callable=AsyncMock),
            patch("backend.main.get_executor_instance", return_value=executor),
            patch("backend.ha_socket.start_ha_socket_client"),
            patch("backend.ha_socket.stop_ha_socket_client"),
            patch("ml.price_forecast.cleanup_price_forecast_duplicates", return_value=0),
            patch("backend.learning.base_load_migration.flag_historical_base_load", migration),
        ):
            stack.enter_context(p)
        async with lifespan(FastAPI()) as _:
            pass
    migration.assert_called_once()
    assert migration.call_args.args[0] == str(db_path)


def test_fresh_database_without_schema_logs_no_error(tmp_path, caplog):
    path = str(tmp_path / "fresh.db")
    sqlite3.connect(path).close()
    with caplog.at_level(logging.DEBUG, logger="darkstar.learning.base_load_migration"):
        assert flag_historical_base_load(path, CONFIG) is None
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_empty_database_completes_without_warning_and_stays_idempotent(db, caplog):
    with caplog.at_level(logging.DEBUG, logger="darkstar.learning.base_load_migration"):
        assert flag_historical_base_load(db, CONFIG) == {
            "a": 0,
            "after_clamp": 0,
            "b": 0,
            "skipped_unparseable": 0,
        }
        assert flag_historical_base_load(db, CONFIG) is None
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT 1 FROM system_state WHERE key = ?", (STATE_KEY,)).fetchone()
