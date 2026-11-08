"""A water sensor that is unavailable keeps recorder-owned `unknown` provenance end to end.

Recorder -> real store -> grid-only comparison, over the shape of a real outage
(sensor unavailable 08:00:26 to 12:23:50 local).
"""

import json
import sqlite3
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytz

from backend.grid_only_comparison import GridOnlyObservation, build_grid_only_comparison
from backend.learning.models import Base
from backend.learning.store import LearningStore
from backend.recorder import record_observation_from_current_state

TZ = pytz.timezone("Europe/Stockholm")
DAY = datetime(2026, 11, 5)
SLOT = timedelta(minutes=15)
PRICES = {"import_price_sek_kwh": 2.0, "export_price_sek_kwh": 1.0}


def local(hour: int, minute: int = 0) -> datetime:
    return TZ.localize(DAY.replace(hour=hour, minute=minute))


def config(db_path, **overrides) -> dict:
    result = {
        "timezone": "Europe/Stockholm",
        "learning": {"sqlite_path": str(db_path)},
        "input_sensors": {"load_power": "sensor.load", "grid_power": "sensor.grid"},
        "system": {
            "grid_meter_type": "net",
            "has_solar": False,
            "has_battery": False,
            "has_water_heater": True,
            "has_ev_charger": False,
        },
        "water_heaters": [{"id": "tank", "enabled": True, "sensor": "sensor.wh"}],
        "ev_chargers": [],
    }
    result.update(overrides)
    return result


def states(entity: str, slot_start: datetime, points: list[tuple[float, str]]) -> list[dict]:
    """HA history states: (seconds after slot start, state string)."""
    return [
        {
            "entity_id": entity,
            "state": state,
            "last_changed": (slot_start + timedelta(seconds=sec)).isoformat(),
            "attributes": {"unit_of_measurement": "kW"},
        }
        for sec, state in points
    ]


async def record_slot(
    db_path,
    slot_start: datetime,
    *,
    water: list[tuple[float, str]] | None,
    water_snapshot: float | None = None,
    load: list[tuple[float, str]] | None = ((0, "2.0"),),
    load_snapshot: float = 2.0,
    extra_history: dict | None = None,
    extra_snapshots: dict | None = None,
    cfg: dict | None = None,
) -> None:
    now = slot_start + SLOT + timedelta(seconds=5)

    class _Now(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    history: dict[str, list[dict]] = {
        "sensor.grid": states("sensor.grid", slot_start, [(0, "2.0")]),
        "sensor.load": states("sensor.load", slot_start, list(load)) if load else [],
        "sensor.wh": states("sensor.wh", slot_start, water) if water else [],
    }
    history.update(extra_history or {})
    snapshots = {"sensor.grid": 2.0, "sensor.load": load_snapshot, "sensor.wh": water_snapshot}
    snapshots.update(extra_snapshots or {})

    async def fake_history(entity_ids, start, end, **_kwargs):
        return {entity: history.get(entity, []) for entity in entity_ids}

    async def snapshot(entity):
        return snapshots.get(entity)

    with (
        patch("backend.recorder.datetime", _Now),
        patch("backend.recorder.get_power_history_batch", AsyncMock(side_effect=fake_history)),
        patch("backend.recorder.get_ha_sensor_kw_normalized", side_effect=snapshot),
        patch("backend.recorder.get_ha_sensor_float", return_value=None),
        patch("backend.recorder.get_current_slot_prices", AsyncMock(return_value=PRICES)),
    ):
        await record_observation_from_current_state(config=cfg or config(db_path))


async def make_db(tmp_path):
    db_path = tmp_path / "learning.db"
    store = LearningStore(str(db_path), TZ)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await store.close()
    return db_path


def stored_rows(db_path) -> dict[datetime, dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM slot_observations ORDER BY slot_start").fetchall()
    return {datetime.fromisoformat(r["slot_start"]): dict(r) for r in rows}


def components(row: dict) -> dict:
    return json.loads(row["quality_flags"])["recording"]["components"]


def observations(rows: dict[datetime, dict]) -> list[GridOnlyObservation]:
    return [
        GridOnlyObservation(
            start=start,
            import_kwh=row["import_kwh"],
            export_kwh=row["export_kwh"],
            import_price_sek_kwh=row["import_price_sek_kwh"],
            export_price_sek_kwh=row["export_price_sek_kwh"],
            load_kwh=row["load_kwh"],
            water_kwh=row["water_kwh"],
            ev_charging_kwh=row["ev_charging_kwh"],
            batt_charge_kwh=row["batt_charge_kwh"],
            batt_discharge_kwh=row["batt_discharge_kwh"],
            quality_flags=row["quality_flags"],
        )
        for start, row in rows.items()
    ]


def compare(rows: dict[datetime, dict], first: datetime, count: int) -> dict:
    starts = [first + SLOT * i for i in range(count)]
    return build_grid_only_comparison(
        observations(rows),
        starts,
        timezone=TZ,
        hourly=True,
        axis_start=starts[0],
        axis_end=starts[-1] + SLOT,
        has_completed_observations=bool(rows),
    )


async def record_outage(db_path) -> None:
    """08:00 (valid then unavailable), 08:15-12:00 (fully unavailable), 12:15 (back at 12:23:50)."""
    await record_slot(
        db_path, local(8), water=[(0, "2.0"), (26, "unavailable")], water_snapshot=None
    )
    slot = local(8, 15)
    while slot < local(12, 15):
        await record_slot(db_path, slot, water=[(0, "unavailable")], water_snapshot=None)
        slot += SLOT
    await record_slot(
        db_path,
        local(12, 15),
        water=[(0, "unavailable"), (518, "2.0")],
        water_snapshot=2.0,
    )


@pytest.mark.asyncio
async def test_fully_unavailable_water_slot_is_recorder_unknown_with_zero_value(tmp_path):
    db_path = await make_db(tmp_path)
    await record_slot(db_path, local(9), water=[(0, "unavailable")], water_snapshot=None)
    (row,) = stored_rows(db_path).values()
    water = components(row)["water"]
    assert (water["method"], water["owner"]) == ("unknown", "recorder")
    assert row["water_kwh"] == 0.0
    assert components(row)["load"]["method"] == "derived_history"
    assert row["load_kwh"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_outage_window_is_one_covered_segment_with_exact_baseline(tmp_path):
    db_path = await make_db(tmp_path)
    await record_outage(db_path)
    rows = stored_rows(db_path)
    result = compare(rows, local(8), 18)

    assert result["status"] == "available"
    assert result["coverage"]["covered_slots"] == 18
    assert result["coverage"]["excluded_slots"] == 0
    assert result["coverage"]["water_unmeasured_slots"] == 16
    assert result["excluded_spans"] == []
    assert len(result["segments"]) == 1
    expected = sum(
        (r["load_kwh"] + r["water_kwh"] + r["ev_charging_kwh"]) * r["import_price_sek_kwh"]
        for r in rows.values()
    )
    assert result["grid_only_cost_sek"] == pytest.approx(round(expected, 3))
    unknown_rows = [r for s, r in rows.items() if local(8, 15) <= s < local(12, 15)]
    assert len(unknown_rows) == 16
    assert all(r["water_kwh"] == 0.0 for r in unknown_rows)
    # The unmeasured water sits in the derived load: (load + ev) * price is the bill.
    assert sum(
        (r["load_kwh"] + r["ev_charging_kwh"]) * r["import_price_sek_kwh"] for r in unknown_rows
    ) == pytest.approx(16 * 0.5 * 2.0)


@pytest.mark.asyncio
async def test_boundary_slots_stay_power_history_without_a_water_note(tmp_path):
    db_path = await make_db(tmp_path)
    await record_outage(db_path)
    rows = stored_rows(db_path)
    for hour, minute in ((8, 0), (12, 15)):
        row = rows[local(hour, minute)]
        assert components(row)["water"]["method"] == "power_history"
        assert components(row)["water"]["owner"] == "recorder"
    assert rows[local(12, 15)]["water_kwh"] == pytest.approx(2.0 * (900 - 518) / 3600)
    for hour, minute in ((8, 15), (12, 0)):
        assert components(rows[local(hour, minute)])["water"]["method"] == "unknown"
    # Boundary slots alone carry no water note; the 16 unknown slots in between do.
    only_boundaries = {s: r for s, r in rows.items() if s in (local(8), local(12, 15))}
    assert compare(only_boundaries, local(8), 1)["coverage"]["water_unmeasured_slots"] == 0
    assert compare(only_boundaries, local(12, 15), 1)["coverage"]["water_unmeasured_slots"] == 0


@pytest.mark.asyncio
async def test_unknown_water_with_snapshot_load_stays_excluded(tmp_path):
    db_path = await make_db(tmp_path)
    await record_slot(db_path, local(9), water=[(0, "unavailable")], water_snapshot=None, load=None)
    rows = stored_rows(db_path)
    assert components(rows[local(9)])["load"]["method"] in {"snapshot", "mixed"}
    result = compare(rows, local(9), 1)
    assert result["coverage"]["covered_slots"] == 0
    assert result["excluded_spans"][0]["reason"] == "estimated_component"


@pytest.mark.asyncio
async def test_unknown_water_with_ev_and_zero_load_stays_excluded(tmp_path):
    db_path = await make_db(tmp_path)
    cfg = config(
        db_path,
        system={
            "grid_meter_type": "net",
            "has_solar": False,
            "has_battery": False,
            "has_water_heater": True,
            "has_ev_charger": True,
        },
        ev_chargers=[{"id": "ev1", "enabled": True, "sensor": "sensor.ev"}],
    )
    await record_slot(
        db_path,
        local(9),
        water=[(0, "unavailable")],
        load=[(0, "0.4")],
        extra_history={"sensor.ev": states("sensor.ev", local(9), [(0, "2.0")])},
        extra_snapshots={"sensor.ev": 2.0},
        cfg=cfg,
    )
    row = stored_rows(db_path)[local(9)]
    assert row["ev_charging_kwh"] > 0 and row["load_kwh"] == 0
    result = compare(stored_rows(db_path), local(9), 1)
    assert result["coverage"]["covered_slots"] == 0
    assert result["excluded_spans"][0]["reason"] == "clamp_hidden_demand"


@pytest.mark.asyncio
async def test_unknown_water_with_unknown_ev_stays_excluded(tmp_path):
    db_path = await make_db(tmp_path)
    await record_slot(db_path, local(9), water=[(0, "unavailable")], water_snapshot=None)
    rows = stored_rows(db_path)
    flags = json.loads(rows[local(9)]["quality_flags"])
    flags["recording"]["components"]["ev"]["method"] = "unknown"
    rows[local(9)]["quality_flags"] = json.dumps(flags)
    result = compare(rows, local(9), 1)
    assert result["coverage"]["covered_slots"] == 0
    assert (result["excluded_spans"][0]["reason"], result["excluded_spans"][0]["component"]) == (
        "unknown_component",
        "ev",
    )


@pytest.mark.asyncio
async def test_unknown_load_stays_excluded_whatever_the_water(tmp_path):
    db_path = await make_db(tmp_path)
    await record_slot(db_path, local(9), water=[(0, "unavailable")], water_snapshot=None)
    rows = stored_rows(db_path)
    flags = json.loads(rows[local(9)]["quality_flags"])
    flags["recording"]["components"]["load"]["method"] = "unknown"
    rows[local(9)]["quality_flags"] = json.dumps(flags)
    result = compare(rows, local(9), 1)
    assert result["coverage"]["covered_slots"] == 0
    assert result["excluded_spans"][0]["reason"] == "unknown_component"
    assert result["excluded_spans"][0]["component"] == "load"


@pytest.mark.asyncio
async def test_water_unavailable_mid_slot_integrates_only_the_valid_part_and_stays_exact(tmp_path):
    """08:00 shape: 2 kW for 26 s, then unavailable. The hold must not run to the slot end."""
    db_path = await make_db(tmp_path)
    await record_slot(
        db_path,
        local(8),
        water=[(0, "2.0"), (26, "unavailable")],
        water_snapshot=None,
        load=[(0, "3.0")],
        load_snapshot=3.0,
    )
    rows = stored_rows(db_path)
    row = rows[local(8)]
    assert components(row)["water"]["method"] == "power_history"
    assert row["water_kwh"] == pytest.approx(2.0 * 26 / 3600)
    assert row["water_kwh"] < 0.015
    total = 3.0 * 0.25
    assert row["load_kwh"] + row["water_kwh"] + row["ev_charging_kwh"] == pytest.approx(total)
    assert components(row)["load"]["method"] == "derived_history"

    result = compare(rows, local(8), 1)
    assert result["coverage"]["covered_slots"] == 1
    assert result["coverage"]["water_unmeasured_slots"] == 0
    assert result["grid_only_cost_sek"] == pytest.approx(round(total * 2.0, 3))


@pytest.mark.asyncio
async def test_water_returning_mid_slot_and_flapping_stay_exact(tmp_path):
    """12:15 shape and several flaps: water integrates valid intervals, the bill stays exact."""
    db_path = await make_db(tmp_path)
    await record_slot(
        db_path,
        local(12, 15),
        water=[(0, "unavailable"), (518, "2.0")],
        water_snapshot=2.0,
        load=[(0, "3.0")],
    )
    await record_slot(
        db_path,
        local(12, 30),
        water=[(0, "2.0"), (120, "unknown"), (300, "2.0"), (600, "unavailable"), (750, "2.0")],
        water_snapshot=2.0,
        load=[(0, "3.0")],
    )
    rows = stored_rows(db_path)
    returning = rows[local(12, 15)]
    flapping = rows[local(12, 30)]
    assert returning["water_kwh"] == pytest.approx(2.0 * (900 - 518) / 3600)
    assert flapping["water_kwh"] == pytest.approx(2.0 * (120 + 300 + 150) / 3600)
    for row in (returning, flapping):
        assert components(row)["water"]["method"] == "power_history"
        assert row["load_kwh"] + row["water_kwh"] + row["ev_charging_kwh"] == pytest.approx(0.75)
    result = compare(rows, local(12, 15), 2)
    assert result["coverage"]["covered_slots"] == 2
    assert result["grid_only_cost_sek"] == pytest.approx(round(2 * 0.75 * 2.0, 3))
