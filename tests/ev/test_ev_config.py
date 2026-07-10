"""Tests for EV charger config parsing.

Charging goals (target SoC, ready-by, repeat, n_days, keep_on_after_target)
are set in the dashboard and stored in data/ev_multi_day_state.json — config.yaml
carries only hardware facts and HA entity mappings. Any legacy goal field found
in an ev_chargers[] entry is ignored with a deprecation warning, never parsed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from executor.config import EVChargerDeviceConfig, load_executor_config

MINIMAL_CONFIG: dict[str, Any] = {
    "config_version": 2,
    "timezone": "Europe/Stockholm",
    "system": {
        "has_solar": True,
        "has_battery": True,
        "has_water_heater": True,
        "has_ev_charger": True,
    },
    "battery": {"capacity_kwh": 10},
    "battery_economics": {"battery_cycle_cost_kwh": 0.1},
    "executor": {"enabled": False},
}


def _write_config(path: str, data: dict[str, Any]) -> None:
    from ruamel.yaml import YAML

    yaml = YAML(typ="safe")
    yaml.default_flow_style = False
    with Path(path).open("w", encoding="utf-8") as f:
        yaml.dump(data, f)


def _load(data: dict[str, Any]) -> Any:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        path = f.name
    try:
        _write_config(path, data)
        return load_executor_config(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_goal_fields_are_not_parsed() -> None:
    """Config no longer carries goal state; the dataclass has no such fields."""
    data = {
        **MINIMAL_CONFIG,
        "ev_chargers": [
            {
                "id": "ev1",
                "enabled": True,
                "battery_capacity_kwh": 50,
                "target_soc_percent": 80,
                "ready_by": "07:00",
                "repeat": "daily",
                "keep_on_after_target": True,
            }
        ],
    }
    cfg = _load(data)
    ev = cfg.ev_chargers[0]
    assert not hasattr(ev, "target_soc_percent")
    assert not hasattr(ev, "ready_by")
    assert not hasattr(ev, "repeat")
    assert not hasattr(ev, "keep_on_after_target")
    assert ev.battery_capacity_kwh == 50


def test_all_legacy_goal_fields_load_cleanly_with_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    data = {
        **MINIMAL_CONFIG,
        "ev_chargers": [
            {
                "id": "ev1",
                "enabled": True,
                "target_soc_percent": 80,
                "ready_by": "07:00",
                "repeat": "daily",
                "n_days": 2,
                "ready_by_date": "2026-06-12",
                "keep_on_after_target": True,
                "departure_time": "08:00",
                "penalty_levels": [{"max_soc": 90, "penalty_sek": 1}],
            }
        ],
    }
    with caplog.at_level("WARNING"):
        cfg = _load(data)

    assert len(cfg.ev_chargers) == 1
    # Exactly one deprecation warning is logged for this charger, naming the dashboard.
    deprecation_warnings = [
        r
        for r in caplog.records
        if "ev1" in r.getMessage() and "dashboard" in r.getMessage().lower()
    ]
    assert len(deprecation_warnings) == 1


def test_malformed_goal_field_values_do_not_raise() -> None:
    data = {
        **MINIMAL_CONFIG,
        "ev_chargers": [
            {
                "id": "ev1",
                "enabled": True,
                "target_soc_percent": "80%",
                "repeat": 12345,
                "ready_by_date": {"nested": True},
                "n_days": "two",
            }
        ],
    }
    cfg = _load(data)
    assert len(cfg.ev_chargers) == 1
    assert cfg.ev_chargers[0].id == "ev1"


def test_ha_entity_fields_parse() -> None:
    data = {
        **MINIMAL_CONFIG,
        "ev_chargers": [
            {
                "id": "ev1",
                "enabled": True,
                "ha_ready_by_entity": "input_datetime.ev_ready_by",
                "ha_target_soc_entity": "input_number.ev_target_soc",
            },
            {
                "id": "ev2",
                "enabled": True,
                "ha_ready_by_entity": "",
                "ha_target_soc_entity": "   ",
            },
            {
                "id": "ev3",
                "enabled": True,
            },
        ],
    }
    cfg = _load(data)

    ev1 = cfg.ev_chargers[0]
    assert ev1.ha_ready_by_entity == "input_datetime.ev_ready_by"
    assert ev1.ha_target_soc_entity == "input_number.ev_target_soc"

    ev2 = cfg.ev_chargers[1]
    assert ev2.ha_ready_by_entity is None
    assert ev2.ha_target_soc_entity is None

    ev3 = cfg.ev_chargers[2]
    assert ev3.ha_ready_by_entity is None
    assert ev3.ha_target_soc_entity is None


def test_hardware_fields_unaffected_by_deprecated_fields() -> None:
    """battery_capacity_kwh etc. still parse normally alongside ignored goal fields."""
    data = {
        **MINIMAL_CONFIG,
        "ev_chargers": [
            {
                "id": "ev1",
                "enabled": True,
                "max_power_kw": 11.0,
                "battery_capacity_kwh": 82.0,
                "target_soc_percent": 80,
            }
        ],
    }
    cfg = _load(data)
    ev = cfg.ev_chargers[0]
    assert ev.max_power_kw == 11.0
    assert ev.battery_capacity_kwh == 82.0
    assert isinstance(ev, EVChargerDeviceConfig)
