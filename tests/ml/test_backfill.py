"""Backfill integrates the same power history as the live recorder."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
import pytz

from backend.learning.backfill import BackfillEngine

TZ = pytz.timezone("Europe/Stockholm")
NOW = TZ.localize(datetime(2026, 10, 1, 11, 7, 30))


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


def make_config(**overrides) -> dict:
    config = {
        "timezone": "Europe/Stockholm",
        "input_sensors": {
            "pv_power": "sensor.pv",
            "load_power": "sensor.load",
            "grid_power": "sensor.grid",
            "battery_power": "sensor.batt",
            "battery_soc": "sensor.soc",
        },
        "system": {
            "grid_meter_type": "net",
            "has_solar": True,
            "has_battery": True,
            "has_ev_charger": True,
            "has_water_heater": True,
            "grid": {"max_power_kw": 20.0},
        },
        "ev_chargers": [{"id": "ev1", "sensor": "sensor.ev", "enabled": True}],
        "water_heaters": [{"id": "wh1", "sensor": "sensor.wh", "enabled": True}],
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key] = {**config[key], **value}
        else:
            config[key] = value
    return config


def constant_history(values: dict[str, float]):
    """HA-like history: each entity holds one constant value, reported at the window start."""

    async def fake(entity_ids, start, end, **_kwargs):
        return {
            entity: (
                [
                    {
                        "entity_id": entity,
                        "state": str(values[entity]),
                        "last_changed": start.isoformat(),
                        "attributes": {
                            "unit_of_measurement": "%" if entity == "sensor.soc" else "kW"
                        },
                    }
                ]
                if entity in values
                else []
            )
            for entity in entity_ids
        }

    return fake


@pytest.fixture
def make_engine():
    def build(config: dict, last_obs: datetime | None):
        with (
            patch("backend.learning.backfill.get_learning_engine") as get_engine,
            patch("backend.learning.backfill.BackfillEngine._load_config", return_value=config),
        ):
            learning_engine = MagicMock()
            learning_engine.store.get_last_observation_time = AsyncMock(return_value=last_obs)
            learning_engine.store_slot_observations = AsyncMock()
            get_engine.return_value = learning_engine
            return BackfillEngine("dummy_config.yaml"), learning_engine

    return build


async def run(engine: BackfillEngine, history) -> AsyncMock:
    history_mock = AsyncMock(side_effect=history)
    with (
        patch("backend.learning.backfill.datetime", _FixedDateTime),
        patch("backend.learning.backfill.get_power_history_batch", history_mock),
    ):
        await engine.run()
    return history_mock


def stored(learning_engine) -> pd.DataFrame:
    return learning_engine.store_slot_observations.call_args.args[0]


@pytest.mark.asyncio
async def test_no_gap_does_nothing(make_engine):
    engine, learning_engine = make_engine(make_config(), NOW - timedelta(minutes=5))
    history_mock = await run(engine, constant_history({}))
    history_mock.assert_not_awaited()
    learning_engine.store_slot_observations.assert_not_awaited()


@pytest.mark.asyncio
async def test_gap_is_filled_from_power_history_including_battery(make_engine):
    last_obs = TZ.localize(datetime(2026, 10, 1, 8, 0))
    engine, learning_engine = make_engine(make_config(), last_obs)
    history = constant_history(
        {
            "sensor.pv": 4.0,
            "sensor.load": 6.0,
            "sensor.grid": -2.0,
            "sensor.batt": -2.0,
            "sensor.ev": 4.0,
            "sensor.wh": 1.0,
            "sensor.soc": 55.0,
        }
    )
    await run(engine, history)

    df = stored(learning_engine)
    assert learning_engine.store_slot_observations.call_args.kwargs == {"authoritative": False}
    starts = list(df["slot_start"])
    assert starts[0] == TZ.localize(datetime(2026, 10, 1, 8, 15))
    assert starts[-1] == TZ.localize(datetime(2026, 10, 1, 10, 45))
    assert len(df) == 11
    row = df.iloc[0]
    assert row["pv_kwh"] == pytest.approx(1.0)
    assert row["export_kwh"] == pytest.approx(0.5)
    assert row["import_kwh"] == 0.0
    assert row["batt_charge_kwh"] == pytest.approx(0.5)
    assert row["batt_discharge_kwh"] == 0.0
    assert row["ev_charging_kwh"] == pytest.approx(1.0)
    assert row["water_kwh"] == pytest.approx(0.25)
    # total load 6 kW = 1.5 kWh, minus EV 1.0 and water 0.25
    assert row["load_kwh"] == pytest.approx(0.25)
    assert row["soc_start_percent"] == 55.0
    assert row["soc_end_percent"] == 55.0
    assert row["duration_minutes"] == 15


@pytest.mark.asyncio
async def test_load_isolation_clamps_negative_base_load(make_engine):
    engine, learning_engine = make_engine(make_config(), TZ.localize(datetime(2026, 10, 1, 10, 0)))
    await run(engine, constant_history({"sensor.load": 2.0, "sensor.ev": 8.0}))
    assert stored(learning_engine).iloc[0]["load_kwh"] == 0.0


@pytest.mark.asyncio
async def test_inversion_flags_apply(make_engine):
    config = make_config(
        input_sensors={"grid_power_inverted": True, "battery_power_inverted": True}
    )
    engine, learning_engine = make_engine(config, TZ.localize(datetime(2026, 10, 1, 10, 0)))
    await run(engine, constant_history({"sensor.grid": -3.0, "sensor.batt": 2.0}))
    row = stored(learning_engine).iloc[0]
    assert row["import_kwh"] == pytest.approx(0.75)
    assert row["export_kwh"] == 0.0
    assert row["batt_charge_kwh"] == pytest.approx(0.5)
    assert row["batt_discharge_kwh"] == 0.0


@pytest.mark.asyncio
async def test_spike_is_filtered_with_config_threshold(make_engine):
    config = make_config(system={"grid": {"max_power_kw": 10.0}})  # 5 kWh per slot
    engine, learning_engine = make_engine(config, TZ.localize(datetime(2026, 10, 1, 10, 0)))
    await run(engine, constant_history({"sensor.pv": 100.0, "sensor.load": 4.0}))
    row = stored(learning_engine).iloc[0]
    assert row["pv_kwh"] == 0.0
    assert row["load_kwh"] == pytest.approx(1.0)
    assert row["quality_flags"]["recording"]["components"]["pv"]["method"] == "unknown"


@pytest.mark.asyncio
async def test_disabled_battery_is_not_requested(make_engine):
    config = make_config(system={"has_battery": False})
    engine, learning_engine = make_engine(config, TZ.localize(datetime(2026, 10, 1, 10, 0)))
    history_mock = await run(engine, constant_history({"sensor.batt": -2.0, "sensor.load": 1.0}))
    assert "sensor.batt" not in history_mock.await_args.args[0]
    row = stored(learning_engine).iloc[0]
    assert row["batt_charge_kwh"] == 0.0
    assert row["batt_discharge_kwh"] == 0.0


@pytest.mark.asyncio
async def test_entity_without_history_is_not_measured(make_engine):
    engine, learning_engine = make_engine(make_config(), TZ.localize(datetime(2026, 10, 1, 10, 0)))
    await run(engine, constant_history({"sensor.load": 1.0}))
    row = stored(learning_engine).iloc[0]
    assert pd.isna(row["pv_kwh"])
    assert row["load_kwh"] == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_requests_are_batched_one_per_local_day(make_engine):
    # 3-day gap ending 11:07 on 10-01: days 09-28, 09-29, 09-30, 10-01 are touched
    last_obs = TZ.localize(datetime(2026, 9, 28, 20, 0))
    engine, learning_engine = make_engine(make_config(), last_obs)
    history_mock = await run(engine, constant_history({"sensor.load": 1.0}))

    assert history_mock.await_count == 4
    for call in history_mock.await_args_list:
        entities, start, end = call.args
        assert end - start <= timedelta(days=1)
        assert len(entities) == len(set(entities))
        assert "sensor.load" in entities
    # 2026-09-28 20:15 through 2026-10-01 10:45
    assert len(stored(learning_engine)) == 251


@pytest.mark.asyncio
async def test_gap_older_than_ten_days_is_capped(make_engine):
    engine, learning_engine = make_engine(make_config(), NOW - timedelta(days=14))
    history_mock = await run(engine, constant_history({"sensor.load": 1.0}))
    df = stored(learning_engine)
    assert min(df["slot_start"]) >= NOW - timedelta(days=10)
    assert min(df["slot_start"]) < NOW - timedelta(days=10) + timedelta(minutes=15)
    assert history_mock.await_count <= 11


@pytest.mark.asyncio
async def test_empty_database_backfills_seven_days(make_engine):
    engine, learning_engine = make_engine(make_config(), None)
    await run(engine, constant_history({"sensor.load": 1.0}))
    df = stored(learning_engine)
    assert min(df["slot_start"]) >= NOW - timedelta(days=7)
    assert min(df["slot_start"]) < NOW - timedelta(days=7) + timedelta(minutes=15)


@pytest.mark.asyncio
async def test_failed_request_stores_nothing(make_engine):
    engine, learning_engine = make_engine(make_config(), TZ.localize(datetime(2026, 10, 1, 10, 0)))

    async def failing(entity_ids, start, end, **_kwargs):
        return None

    await run(engine, failing)
    learning_engine.store_slot_observations.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_history_at_all_stores_nothing(make_engine):
    engine, learning_engine = make_engine(make_config(), TZ.localize(datetime(2026, 10, 1, 10, 0)))
    await run(engine, constant_history({}))
    learning_engine.store_slot_observations.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_power_sensors_configured_does_nothing(make_engine):
    config = make_config(input_sensors={}, ev_chargers=[], water_heaters=[])
    config["input_sensors"] = {}
    engine, learning_engine = make_engine(config, TZ.localize(datetime(2026, 10, 1, 10, 0)))
    history_mock = await run(engine, constant_history({}))
    history_mock.assert_not_awaited()
    learning_engine.store_slot_observations.assert_not_awaited()


@pytest.mark.asyncio
async def test_unconfigured_enabled_device_taints_backfill_aggregate_and_derived_load(make_engine):
    config = make_config(
        ev_chargers=[
            {"id": "configured", "sensor": "sensor.ev", "enabled": True},
            {"id": "missing", "enabled": True},
        ]
    )
    engine, learning_engine = make_engine(config, TZ.localize(datetime(2026, 10, 1, 10, 0)))
    await run(engine, constant_history({"sensor.load": 4.0, "sensor.ev": 1.0, "sensor.wh": 0.0}))
    row = stored(learning_engine).iloc[0]
    components = row["quality_flags"]["recording"]["components"]
    assert components["ev"]["method"] == "mixed"
    assert components["load"]["method"] == "mixed"
    assert components["ev"]["owner"] == "backfill"


@pytest.mark.asyncio
async def test_all_disabled_devices_have_disabled_zero_backfill_provenance(make_engine):
    config = make_config(
        ev_chargers=[{"id": "ev", "enabled": False}],
        water_heaters=[{"id": "wh", "enabled": False}],
    )
    engine, learning_engine = make_engine(config, TZ.localize(datetime(2026, 10, 1, 10, 0)))
    await run(engine, constant_history({"sensor.load": 4.0}))
    row = stored(learning_engine).iloc[0]
    components = row["quality_flags"]["recording"]["components"]
    assert row["ev_charging_kwh"] == row["water_kwh"] == 0.0
    assert components["ev"]["method"] == components["water"]["method"] == "disabled_zero"
    assert components["load"]["method"] == "derived_history"


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_heater", [False, True])
async def test_water_cutoff_backfill_retains_idle_load_and_truthful_coverage(
    make_engine, missing_heater
):
    heaters = [{"id": "tank", "sensor": "sensor.wh", "idle_power_threshold_kw": 0.1}]
    if missing_heater:
        heaters.append({"id": "unknown"})
    config = make_config(water_heaters=heaters)
    engine, learning_engine = make_engine(config, TZ.localize(datetime(2026, 10, 1, 10)))
    await run(
        engine,
        constant_history({"sensor.load": 4, "sensor.wh": 0.06, "sensor.ev": 0, "sensor.grid": 4}),
    )
    row = stored(learning_engine).iloc[0]
    assert row["water_kwh"] == 0
    assert row["load_kwh"] == 1
    assert row["import_kwh"] == 1
    metadata = row["quality_flags"]
    assert metadata["water_heater_energy"]["devices"]["tank"]["energy_kwh"] == 0
    assert metadata["recording"]["components"]["water"]["method"] == (
        "unknown" if missing_heater else "power_history"
    )
