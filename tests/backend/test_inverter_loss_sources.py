"""Optional inverter-loss sensor: source registration and slot integration."""

from datetime import datetime, timedelta

import pytest
import pytz

from backend.core.ha_client import parse_power_states
from backend.core.power_sensors import INVERTER_POWER_LOSSES, POWER_SENSOR_PATHS
from backend.core.slot_energy import build_slot_sources, compute_slot_energy

BASE = datetime(2026, 11, 5, 8, 0, tzinfo=pytz.UTC)
SLOT = timedelta(minutes=15)
CONFIG = {
    "system": {"has_battery": True, "has_solar": True, "grid_meter_type": "net"},
    "input_sensors": {
        "pv_power": "sensor.pv",
        "load_power": "sensor.load",
        "grid_power": "sensor.grid",
        "battery_power": "sensor.batt",
    },
}


def _with_loss_sensor(entity: str = "sensor.loss") -> dict:
    return {**CONFIG, "input_sensors": {**CONFIG["input_sensors"], "inverter_power_losses": entity}}


def _states(points: list[tuple[float, str]], unit: str = "kW") -> list[dict]:
    return [
        {
            "state": state,
            "last_changed": (BASE + timedelta(seconds=sec)).isoformat(),
            "attributes": {"unit_of_measurement": unit},
        }
        for sec, state in points
    ]


def test_unconfigured_sensor_adds_no_entity_to_the_history_request() -> None:
    sources = build_slot_sources(CONFIG)

    assert sources.inverter_loss is None
    assert sorted(sources.entity_ids()) == [
        "sensor.batt",
        "sensor.grid",
        "sensor.load",
        "sensor.pv",
    ]


def test_empty_string_counts_as_unconfigured() -> None:
    assert build_slot_sources(_with_loss_sensor("")).inverter_loss is None


def test_configured_sensor_is_one_more_batched_entity() -> None:
    sources = build_slot_sources(_with_loss_sensor())

    assert sources.inverter_loss == "sensor.loss"
    assert sources.entity_ids().count("sensor.loss") == 1
    assert len(sources.entity_ids()) == 5


def test_sensor_is_ignored_without_a_battery() -> None:
    config = _with_loss_sensor()
    config["system"] = {**config["system"], "has_battery": False}

    assert build_slot_sources(config).inverter_loss is None


def test_sensor_is_registered_as_a_power_sensor_for_unit_selection() -> None:
    entry = POWER_SENSOR_PATHS[INVERTER_POWER_LOSSES]
    assert entry.patterns == ("input_sensors.inverter_power_losses",)


def test_full_coverage_integrates_the_slot_loss() -> None:
    sources = build_slot_sources(_with_loss_sensor())
    series = {"sensor.loss": parse_power_states(_states([(0, "0.16")]))}

    assert compute_slot_energy(sources, series, BASE, BASE + SLOT).inverter_loss == pytest.approx(
        0.04
    )


def test_unavailable_or_missing_history_gives_no_value() -> None:
    sources = build_slot_sources(_with_loss_sensor())
    unavailable = {"sensor.loss": parse_power_states(_states([(0, "unavailable")]))}

    assert compute_slot_energy(sources, unavailable, BASE, BASE + SLOT).inverter_loss is None
    assert compute_slot_energy(sources, {}, BASE, BASE + SLOT).inverter_loss is None


def test_partly_covered_slot_gives_no_value() -> None:
    sources = build_slot_sources(_with_loss_sensor())
    series = {"sensor.loss": parse_power_states(_states([(0, "unavailable"), (600, "0.16")]))}

    assert compute_slot_energy(sources, series, BASE, BASE + SLOT).inverter_loss is None


def test_watt_sensor_is_scaled() -> None:
    sources = build_slot_sources(_with_loss_sensor())
    series = {"sensor.loss": parse_power_states(_states([(0, "160")], unit="W"))}

    assert compute_slot_energy(sources, series, BASE, BASE + SLOT).inverter_loss == pytest.approx(
        0.04
    )
