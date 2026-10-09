"""Recorder slot energy: every metric is step-integrated from power history."""

import logging
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from backend.recorder import record_observation_from_current_state

TZ = pytz.timezone("Europe/Stockholm")
# Wake just after 00:30 -> the completed slot is [00:15, 00:30]
NOW = TZ.localize(datetime(2026, 10, 1, 0, 30, 5))
SLOT_START = TZ.localize(datetime(2026, 10, 1, 0, 15))
SLOT_END = TZ.localize(datetime(2026, 10, 1, 0, 30))


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


def series(entity: str, points: list[tuple[float, float]], unit: str = "kW") -> list[dict]:
    """HA history states: (seconds after slot start, value)."""
    return [
        {
            "entity_id": entity,
            "state": str(value),
            "last_changed": (SLOT_START + timedelta(seconds=sec)).isoformat(),
            "attributes": {"unit_of_measurement": unit},
        }
        for sec, value in points
    ]


def constant(entity: str, value: float) -> list[dict]:
    return series(entity, [(0, value)])


def base_config(**overrides) -> dict:
    config = {
        "timezone": "Europe/Stockholm",
        "learning": {"sqlite_path": ":memory:"},
        "input_sensors": {
            "pv_power": "sensor.pv",
            "load_power": "sensor.load",
            "grid_power": "sensor.grid",
            "battery_power": "sensor.batt",
        },
        "system": {
            "grid_meter_type": "net",
            "has_solar": True,
            "has_battery": True,
            "has_water_heater": False,
            "has_ev_charger": False,
        },
        "water_heaters": [],
        "ev_chargers": [],
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key] = {**config[key], **value}
        else:
            config[key] = value
    return config


async def record(
    config: dict,
    history: dict[str, list[dict]] | None,
    snapshots: dict[str, float] | None = None,
    disaggregator=None,
    cached_soc: str | None = None,
) -> tuple[dict, AsyncMock]:
    """Run one recorder cycle; returns the stored record and the history mock."""

    async def fake_history(entity_ids, start, end, **_kwargs):
        if history is None:
            return None
        return {entity: history.get(entity, []) for entity in entity_ids}

    history_mock = AsyncMock(side_effect=fake_history)
    snapshot_values = snapshots or {}

    async def snapshot(entity):
        return snapshot_values.get(entity, 0.0)

    store = MagicMock()
    store.get_system_state = AsyncMock(return_value=cached_soc)
    store.set_system_state = AsyncMock()
    store.store_slot_observations = AsyncMock()
    store.close = AsyncMock()

    with (
        patch("backend.recorder.datetime", _FixedDateTime),
        patch("backend.recorder.get_power_history_batch", history_mock),
        patch("backend.recorder.get_ha_sensor_kw_normalized", side_effect=snapshot),
        patch("backend.recorder.get_ha_sensor_float", return_value=None),
        patch("backend.recorder.get_current_slot_prices", return_value=None),
        patch("backend.recorder.LearningStore", return_value=store),
    ):
        await record_observation_from_current_state(config=config, disaggregator=disaggregator)

    df = store.store_slot_observations.call_args[0][0]
    return df.iloc[0].to_dict(), history_mock


class TestIntegratedSlotEnergy:
    @pytest.mark.asyncio
    async def test_load_starting_mid_slot_lands_in_the_slot(self):
        history = {"sensor.grid": series("sensor.grid", [(0, 0.3), (8, 7.2)])}
        record_, _ = await record(base_config(), history)
        expected = 0.3 * 8 / 3600 + 7.2 * 892 / 3600
        assert record_["import_kwh"] == pytest.approx(expected)
        assert record_["export_kwh"] == 0.0

    @pytest.mark.asyncio
    async def test_window_is_exactly_the_completed_slot(self):
        _, history_mock = await record(base_config(), {})
        _entities, start, end = history_mock.await_args.args
        assert (start, end) == (SLOT_START, SLOT_END)

    @pytest.mark.asyncio
    async def test_ev_charge_start_slot_import_covers_the_ev_share(self):
        """2026-10-01 00:15: EV starts 10 s in; the old counters recorded import < EV."""
        config = base_config(
            system={"has_ev_charger": True},
            ev_chargers=[{"id": "ev1", "enabled": True, "sensor": "sensor.ev"}],
        )
        history = {
            "sensor.ev": series("sensor.ev", [(0, 0.0), (10, 6.9)]),
            "sensor.load": series("sensor.load", [(0, 0.25), (10, 7.15)]),
            "sensor.grid": series("sensor.grid", [(0, 0.25), (10, 7.15)]),
            "sensor.pv": constant("sensor.pv", 0.0),
            "sensor.batt": constant("sensor.batt", 0.0),
        }
        record_, _ = await record(config, history)
        assert record_["import_kwh"] >= record_["ev_charging_kwh"]
        assert record_["ev_charging_kwh"] == pytest.approx(6.9 * 890 / 3600)
        assert record_["load_kwh"] == pytest.approx(0.25 * 900 / 3600)

    @pytest.mark.asyncio
    async def test_pv_and_load_come_from_history(self):
        history = {
            "sensor.pv": constant("sensor.pv", 4.0),
            "sensor.load": constant("sensor.load", 2.0),
        }
        record_, _ = await record(base_config(), history, snapshots={"sensor.pv": 99.0})
        assert record_["pv_kwh"] == pytest.approx(1.0)
        assert record_["load_kwh"] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_watt_sensors_are_scaled(self):
        history = {"sensor.pv": series("sensor.pv", [(0, 4000)], unit="W")}
        record_, _ = await record(base_config(), history)
        assert record_["pv_kwh"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_negative_pv_and_load_contribute_zero(self):
        history = {
            "sensor.pv": constant("sensor.pv", -0.5),
            "sensor.load": constant("sensor.load", -0.5),
        }
        record_, _ = await record(base_config(), history)
        assert record_["pv_kwh"] == 0.0
        assert record_["load_kwh"] == 0.0

    @pytest.mark.asyncio
    async def test_component_provenance_distinguishes_integrated_and_snapshot_values(self):
        history = {"sensor.pv": constant("sensor.pv", 2.0)}
        record_, _ = await record(base_config(), history, snapshots={"sensor.batt": 0.0})
        recording = record_["quality_flags"]["recording"]
        assert recording["schema_version"] == 1
        assert recording["components"]["pv"]["method"] == "power_history"
        assert recording["components"]["battery_charge"]["method"] == "snapshot"
        assert recording["components"]["battery_discharge"]["method"] == "snapshot"
        assert recording["soc"]["source"] == "unavailable"
        assert len(recording["boundary_fingerprint"]) == 64

    @pytest.mark.asyncio
    async def test_mixed_device_aggregate_and_base_load_keep_snapshot_provenance(self):
        config = base_config(
            system={"has_ev_charger": True},
            ev_chargers=[
                {"id": "ev1", "enabled": True, "sensor": "sensor.ev1"},
                {"id": "ev2", "enabled": True, "sensor": "sensor.ev2"},
            ],
        )
        history = {
            "sensor.load": constant("sensor.load", 0.5),
            "sensor.ev1": constant("sensor.ev1", 1.0),
        }
        record_, _ = await record(config, history, snapshots={"sensor.ev2": 0.0})
        components = record_["quality_flags"]["recording"]["components"]
        assert components["ev"]["method"] == "mixed"
        assert components["load"]["method"] == "mixed"

    @pytest.mark.asyncio
    async def test_enabled_but_unconfigured_device_is_not_a_disabled_zero(self):
        config = base_config(
            system={"has_ev_charger": True},
            ev_chargers=[{"id": "ev1", "enabled": True}],
        )
        record_, _ = await record(config, {})
        components = record_["quality_flags"]["recording"]["components"]
        assert components["ev"]["method"] == "unconfigured_zero"
        assert components["load"]["method"] == "mixed"

    @pytest.mark.asyncio
    async def test_cached_soc_is_labelled_as_cached(self):
        config = base_config(input_sensors={"battery_soc": "sensor.soc"})
        record_, _ = await record(config, {}, cached_soc="72.5")
        recording = record_["quality_flags"]["recording"]
        assert recording["soc"] == {"owner": "recorder", "source": "cached"}


class TestGridAndBattery:
    @pytest.mark.asyncio
    async def test_net_meter_splits_import_and_export(self):
        history = {"sensor.grid": series("sensor.grid", [(0, 2.0), (300, -4.0)])}
        record_, _ = await record(base_config(), history)
        assert record_["import_kwh"] == pytest.approx(0.1667, abs=1e-4)
        assert record_["export_kwh"] == pytest.approx(0.6667, abs=1e-4)

    @pytest.mark.asyncio
    async def test_inverted_net_meter(self):
        config = base_config(input_sensors={"grid_power_inverted": True})
        history = {"sensor.grid": constant("sensor.grid", -3.0)}
        record_, _ = await record(config, history)
        assert record_["import_kwh"] == pytest.approx(0.75)
        assert record_["export_kwh"] == 0.0

    @pytest.mark.asyncio
    async def test_dual_meter_integrates_both_sensors(self):
        config = base_config(
            input_sensors={
                "grid_import_power": "sensor.imp",
                "grid_export_power": "sensor.exp",
            },
            system={"grid_meter_type": "dual"},
        )
        history = {
            "sensor.imp": constant("sensor.imp", 1.0),
            "sensor.exp": constant("sensor.exp", 0.0),
        }
        record_, history_mock = await record(config, history)
        assert record_["import_kwh"] == pytest.approx(0.25)
        assert record_["export_kwh"] == 0.0
        assert "sensor.grid" not in history_mock.await_args.args[0]

    @pytest.mark.asyncio
    async def test_battery_power_history_gives_charge_and_discharge(self):
        history = {"sensor.batt": series("sensor.batt", [(0, -2.0), (360, 1.0)])}
        record_, _ = await record(base_config(), history)
        assert record_["batt_charge_kwh"] == pytest.approx(0.2)
        assert record_["batt_discharge_kwh"] == pytest.approx(0.15)

    @pytest.mark.asyncio
    async def test_inverted_battery_sensor(self):
        config = base_config(input_sensors={"battery_power_inverted": True})
        history = {"sensor.batt": constant("sensor.batt", 2.0)}
        record_, _ = await record(config, history)
        assert record_["batt_charge_kwh"] == pytest.approx(0.5)
        assert record_["batt_discharge_kwh"] == 0.0


class TestBatchedRequest:
    @pytest.mark.asyncio
    async def test_one_request_for_all_entities(self):
        config = base_config(
            system={"has_ev_charger": True, "has_water_heater": True},
            ev_chargers=[{"id": "ev1", "enabled": True, "sensor": "sensor.ev"}],
            water_heaters=[{"id": "wh1", "enabled": True, "sensor": "sensor.wh"}],
        )
        _, history_mock = await record(config, {})
        assert history_mock.await_count == 1
        assert set(history_mock.await_args.args[0]) == {
            "sensor.pv",
            "sensor.load",
            "sensor.grid",
            "sensor.batt",
            "sensor.ev",
            "sensor.wh",
        }

    @pytest.mark.asyncio
    async def test_failed_request_falls_back_to_snapshots_per_metric(self):
        config = base_config(
            system={"has_water_heater": True},
            water_heaters=[{"id": "wh1", "enabled": True, "sensor": "sensor.wh"}],
        )
        snapshots = {
            "sensor.pv": 4.0,
            "sensor.load": 2.0,
            "sensor.grid": -1.0,
            "sensor.batt": 1.2,
            "sensor.wh": 1.0,
        }
        record_, history_mock = await record(config, None, snapshots)
        assert history_mock.await_count == 1
        assert record_["pv_kwh"] == pytest.approx(1.0)
        assert record_["import_kwh"] == 0.0
        assert record_["export_kwh"] == pytest.approx(0.25)
        assert record_["batt_discharge_kwh"] == pytest.approx(0.3)
        assert record_["batt_charge_kwh"] == 0.0
        assert record_["water_kwh"] == pytest.approx(0.25)
        # total load 2.0 kW snapshot minus water, as before
        assert record_["load_kwh"] == pytest.approx(0.5 - 0.25)

    @pytest.mark.asyncio
    async def test_entity_without_history_falls_back_alone(self):
        history = {
            "sensor.pv": [],
            "sensor.load": constant("sensor.load", 2.0),
            "sensor.grid": constant("sensor.grid", 1.0),
        }
        record_, _ = await record(base_config(), history, snapshots={"sensor.pv": 4.0})
        assert record_["pv_kwh"] == pytest.approx(1.0)  # snapshot x 0.25 h
        assert record_["load_kwh"] == pytest.approx(0.5)  # integrated
        assert record_["import_kwh"] == pytest.approx(0.25)

    @pytest.mark.asyncio
    async def test_battery_snapshot_is_sign_gated(self):
        record_, _ = await record(base_config(), None, snapshots={"sensor.batt": -1.2})
        assert record_["batt_charge_kwh"] == pytest.approx(0.3)
        assert record_["batt_discharge_kwh"] == 0.0

    @pytest.mark.asyncio
    async def test_snapshot_applies_grid_inversion(self):
        config = base_config(input_sensors={"grid_power_inverted": True})
        record_, _ = await record(config, None, snapshots={"sensor.grid": -2.0})
        assert record_["import_kwh"] == pytest.approx(0.5)
        assert record_["export_kwh"] == 0.0


class TestDisabledSubsystems:
    @pytest.mark.asyncio
    async def test_disabled_battery_records_zero_without_request(self):
        config = base_config(system={"has_battery": False})
        record_, history_mock = await record(
            config, {"sensor.batt": constant("sensor.batt", -2.0)}, {"sensor.batt": -2.0}
        )
        assert record_["batt_charge_kwh"] == 0.0
        assert record_["batt_discharge_kwh"] == 0.0
        assert "sensor.batt" not in history_mock.await_args.args[0]

    @pytest.mark.asyncio
    async def test_disabled_solar_records_zero_without_request(self):
        config = base_config(system={"has_solar": False})
        record_, history_mock = await record(config, {}, {"sensor.pv": 4.0})
        assert record_["pv_kwh"] == 0.0
        assert "sensor.pv" not in history_mock.await_args.args[0]

    @pytest.mark.asyncio
    async def test_disabled_water_heater_system_is_not_fetched(self):
        config = base_config(
            system={"has_water_heater": False},
            water_heaters=[{"id": "wh1", "enabled": True, "sensor": "sensor.wh"}],
        )
        record_, history_mock = await record(config, {"sensor.wh": constant("sensor.wh", 3.0)})
        assert "sensor.wh" not in history_mock.await_args.args[0]
        assert record_["water_kwh"] == 0.0

    @pytest.mark.asyncio
    async def test_disabled_ev_charger_and_heater_entries_are_skipped(self):
        config = base_config(
            system={"has_ev_charger": True, "has_water_heater": True},
            ev_chargers=[{"id": "ev1", "enabled": False, "sensor": "sensor.ev"}],
            water_heaters=[{"id": "wh1", "enabled": False, "sensor": "sensor.wh"}],
        )
        row, history_mock = await record(config, {"sensor.load": constant("sensor.load", 1.0)})
        requested = set(history_mock.await_args.args[0])
        assert not requested & {"sensor.ev", "sensor.wh"}
        components = row["quality_flags"]["recording"]["components"]
        assert components["ev"]["method"] == components["water"]["method"] == "disabled_zero"
        assert components["load"]["method"] == "derived_history"


class TestLoadIsolation:
    @pytest.fixture
    def config(self):
        return base_config(
            system={"has_ev_charger": True, "has_water_heater": True},
            ev_chargers=[{"id": "ev1", "enabled": True, "sensor": "sensor.ev"}],
            water_heaters=[{"id": "wh1", "enabled": True, "sensor": "sensor.wh"}],
        )

    @pytest.mark.asyncio
    async def test_ev_and_water_subtracted_from_integrated_load(self, config):
        history = {
            "sensor.load": constant("sensor.load", 24.0),  # 6.0 kWh
            "sensor.ev": constant("sensor.ev", 8.0),  # 2.0 kWh
            "sensor.wh": constant("sensor.wh", 3.0),  # 0.75 kWh
        }
        record_, _ = await record(config, history)
        assert record_["load_kwh"] == pytest.approx(3.25)
        assert record_["ev_charging_kwh"] == pytest.approx(2.0)
        assert record_["water_kwh"] == pytest.approx(0.75)

    @pytest.mark.asyncio
    async def test_base_load_never_negative(self, config, caplog):
        history = {
            "sensor.load": constant("sensor.load", 4.0),  # 1.0 kWh
            "sensor.ev": constant("sensor.ev", 8.0),  # 2.0 kWh
        }
        with caplog.at_level(logging.WARNING):
            record_, _ = await record(config, history)
        assert record_["load_kwh"] == 0.0
        assert any("Negative base load" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_no_warning_when_nothing_is_clamped(self, config, caplog):
        history = {
            "sensor.load": constant("sensor.load", 8.0),
            "sensor.ev": constant("sensor.ev", 4.0),
        }
        with caplog.at_level(logging.WARNING):
            await record(config, history)
        assert not any("Negative base load" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_snapshot_load_uses_disaggregated_base_load_without_second_subtraction(
        self, config
    ):
        disaggregator = MagicMock()
        disaggregator.update_current_power = AsyncMock(return_value=4.0)
        disaggregator.calculate_base_load = MagicMock(return_value=2.0)
        history = {"sensor.ev": constant("sensor.ev", 8.0)}  # load has no history
        record_, _ = await record(
            config, history, snapshots={"sensor.load": 6.0}, disaggregator=disaggregator
        )
        assert record_["ev_charging_kwh"] == pytest.approx(2.0)
        assert record_["load_kwh"] == pytest.approx(0.5)  # base 2.0 kW x 0.25 h

    @pytest.mark.asyncio
    async def test_snapshot_load_without_disaggregator_subtracts_deferrable(self, config):
        history = {"sensor.ev": constant("sensor.ev", 4.0)}  # 1.0 kWh
        record_, _ = await record(config, history, snapshots={"sensor.load": 8.0})
        assert record_["load_kwh"] == pytest.approx(2.0 - 1.0)

    @pytest.mark.asyncio
    async def test_disaggregator_does_not_change_integrated_load(self, config):
        disaggregator = MagicMock()
        disaggregator.update_current_power = AsyncMock(return_value=4.0)
        disaggregator.calculate_base_load = MagicMock(return_value=0.1)
        history = {
            "sensor.load": constant("sensor.load", 8.0),
            "sensor.ev": constant("sensor.ev", 4.0),
        }
        record_, _ = await record(config, history, disaggregator=disaggregator)
        assert record_["load_kwh"] == pytest.approx(1.0)


class TestPerDeviceEnergy:
    @pytest.mark.asyncio
    async def test_per_device_values_and_aggregate(self):
        config = base_config(
            system={"has_ev_charger": True, "has_water_heater": True},
            ev_chargers=[
                {"id": "ev1", "enabled": True, "sensor": "sensor.ev1"},
                {"id": "ev2", "enabled": True, "sensor": "sensor.ev2"},
            ],
            water_heaters=[{"id": "wh1", "enabled": True, "sensor": "sensor.wh"}],
        )
        history = {
            "sensor.ev1": constant("sensor.ev1", 4.0),
            "sensor.ev2": constant("sensor.ev2", 2.0),
            "sensor.wh": constant("sensor.wh", 3.0),
        }
        record_, _ = await record(config, history)
        assert record_["ev_charger_energy"] == {
            "ev1": pytest.approx(1.0),
            "ev2": pytest.approx(0.5),
        }
        assert record_["ev_charging_kwh"] == pytest.approx(1.5)
        assert record_["water_heater_energy"] == {"wh1": pytest.approx(0.75)}

    @pytest.mark.asyncio
    async def test_device_without_history_uses_its_snapshot(self):
        config = base_config(
            system={"has_ev_charger": True},
            ev_chargers=[
                {"id": "ev1", "enabled": True, "sensor": "sensor.ev1"},
                {"id": "ev2", "enabled": True, "sensor": "sensor.ev2"},
            ],
        )
        history = {"sensor.ev1": constant("sensor.ev1", 4.0), "sensor.ev2": []}
        record_, _ = await record(config, history, snapshots={"sensor.ev2": 2.0})
        assert record_["ev_charger_energy"] == {
            "ev1": pytest.approx(1.0),
            "ev2": pytest.approx(0.5),
        }

    @pytest.mark.asyncio
    async def test_no_devices_leaves_per_device_empty(self):
        record_, _ = await record(base_config(), {})
        assert record_["ev_charger_energy"] is None
        assert record_["water_heater_energy"] is None


class TestSpikeValidation:
    @pytest.mark.asyncio
    async def test_spike_is_zeroed_before_storage(self):
        config = base_config(system={"grid": {"max_power_kw": 10.0}})  # 5 kWh per slot cap
        history = {
            "sensor.load": constant("sensor.load", 100.0),  # 25 kWh
            "sensor.pv": constant("sensor.pv", 4.0),
        }
        record_, _ = await record(config, history)
        assert record_["load_kwh"] == 0.0
        assert record_["pv_kwh"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_missing_grid_limit_stores_raw_values(self):
        history = {"sensor.pv": constant("sensor.pv", 100.0)}
        record_, _ = await record(base_config(), history)
        assert record_["pv_kwh"] == pytest.approx(25.0)


@pytest.mark.asyncio
async def test_missing_load_sensor_zero_is_unconfigured_not_derived_history():
    config = base_config(input_sensors={"load_power": None})
    row, _ = await record(config, {"sensor.pv": constant("sensor.pv", 0)})
    assert row["quality_flags"]["recording"]["components"]["load"]["method"] == "unconfigured_zero"


@pytest.mark.asyncio
async def test_sanitized_spike_zero_is_not_certified_as_measured_history():
    config = base_config(system={"grid": {"max_power_kw": 10}})
    row, _ = await record(config, {"sensor.load": constant("sensor.load", 100)})
    assert row["load_kwh"] == 0
    assert row["quality_flags"]["recording"]["components"]["load"]["method"] == "unknown"


@pytest.mark.asyncio
async def test_water_cutoff_filters_idle_energy_but_keeps_it_in_base_load():
    config = base_config(
        system={"has_water_heater": True},
        water_heaters=[
            {
                "id": "tank",
                "enabled": True,
                "sensor": "sensor.water",
                "idle_power_threshold_kw": 0.1,
            }
        ],
    )
    history = {
        "sensor.load": series("sensor.load", [(0, 0.06), (300, 3.1)]),
        "sensor.water": series("sensor.water", [(0, 0.06), (300, 3.1)]),
        "sensor.grid": constant("sensor.grid", 1.2),
    }

    row, _ = await record(config, history)

    assert row["water_kwh"] == pytest.approx(3.1 * 600 / 3600)
    assert row["load_kwh"] == pytest.approx(0.06 * 300 / 3600)
    assert row["import_kwh"] == pytest.approx(1.2 * 0.25)
    metadata = row["quality_flags"]["water_heater_energy"]["devices"]["tank"]
    assert metadata == {
        "energy_kwh": pytest.approx(3.1 * 600 / 3600),
        "source": "power_history",
        "idle_power_threshold_kw": 0.1,
        "coverage": "complete",
    }


@pytest.mark.asyncio
async def test_water_measured_zero_and_omitted_cutoff_keep_legacy_semantics():
    config = base_config(
        system={"has_water_heater": True},
        water_heaters=[{"id": "tank", "enabled": True, "sensor": "sensor.water"}],
    )
    zero, _ = await record(config, {"sensor.water": constant("sensor.water", 0.0)})
    idle, _ = await record(config, {"sensor.water": constant("sensor.water", 0.06)})

    zero_metadata = zero["quality_flags"]["water_heater_energy"]["devices"]["tank"]
    assert zero_metadata["energy_kwh"] == 0.0
    assert zero_metadata["coverage"] == "complete"
    assert idle["water_kwh"] == pytest.approx(0.06 * 0.25)


@pytest.mark.asyncio
async def test_water_without_power_sensor_cannot_certify_aggregate_actual():
    config = base_config(
        system={"has_water_heater": True},
        water_heaters=[{"id": "measured", "sensor": "sensor.water"}, {"id": "unmeasured"}],
    )
    recorded, _ = await record(config, {"sensor.water": constant("sensor.water", 3)})
    assert recorded["water_kwh"] == pytest.approx(0.75)
    assert recorded["quality_flags"]["recording"]["components"]["water"]["method"] == "unknown"
    assert recorded["quality_flags"]["water_heater_energy"]["devices"]["measured"][
        "energy_kwh"
    ] == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_unavailable_water_measurement_does_not_write_default_zero():
    config = base_config(
        system={"has_water_heater": True}, water_heaters=[{"id": "tank", "sensor": "sensor.water"}]
    )
    recorded, _ = await record(config, None, snapshots={"sensor.water": None})
    assert recorded["water_kwh"] is None
    assert (
        recorded["quality_flags"]["water_heater_energy"]["devices"]["tank"]["coverage"]
        == "unavailable"
    )
