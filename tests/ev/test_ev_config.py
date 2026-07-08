"""Tests for EV charger config parsing and goal-based field migration."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from executor.config import EVChargerDeviceConfig, EVRepeatMode, load_executor_config


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


def test_default_goal_fields() -> None:
    data = {
        **MINIMAL_CONFIG,
        "ev_chargers": [
            {
                "id": "ev1",
                "enabled": True,
                "battery_capacity_kwh": 50,
            }
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        path = f.name
    try:
        _write_config(path, data)
        cfg = load_executor_config(path)
    finally:
        Path(path).unlink(missing_ok=True)

    ev = cfg.ev_chargers[0]
    assert ev.target_soc_percent == 80
    assert ev.ready_by == "07:00"
    assert ev.repeat == EVRepeatMode.DAILY
    assert ev.keep_on_after_target is False


def test_ready_by_string_and_int() -> None:
    data = {
        **MINIMAL_CONFIG,
        "ev_chargers": [
            {"id": "ev1", "enabled": True, "ready_by": "16:30"},
            {"id": "ev2", "enabled": True, "ready_by": 960},
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        path = f.name
    try:
        _write_config(path, data)
        cfg = load_executor_config(path)
    finally:
        Path(path).unlink(missing_ok=True)

    assert cfg.ev_chargers[0].ready_by == "16:30"
    assert cfg.ev_chargers[1].ready_by == "16:00"


def test_departure_time_alias_warns_and_maps(caplog: pytest.LogCaptureFixture) -> None:
    data = {
        **MINIMAL_CONFIG,
        "ev_chargers": [
            {"id": "ev1", "enabled": True, "departure_time": "08:15"},
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        path = f.name
    try:
        _write_config(path, data)
        cfg = load_executor_config(path)
    finally:
        Path(path).unlink(missing_ok=True)

    ev = cfg.ev_chargers[0]
    assert ev.ready_by == "08:15"
    assert ev.departure_time == "08:15"
    assert "departure_time" in caplog.text
    assert "deprecated" in caplog.text.lower()


def test_penalty_levels_migrates_to_target_soc(caplog: pytest.LogCaptureFixture) -> None:
    data = {
        **MINIMAL_CONFIG,
        "ev_chargers": [
            {
                "id": "ev1",
                "enabled": True,
                "penalty_levels": [
                    {"max_soc": 60, "penalty_sek": 1},
                    {"max_soc": 90, "penalty_sek": 3},
                ],
            }
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        path = f.name
    try:
        _write_config(path, data)
        cfg = load_executor_config(path)
    finally:
        Path(path).unlink(missing_ok=True)

    ev = cfg.ev_chargers[0]
    assert ev.target_soc_percent == 90
    assert "penalty_levels" in caplog.text
    assert "deprecated" in caplog.text.lower()


def test_penalty_levels_ignored_when_target_soc_present(caplog: pytest.LogCaptureFixture) -> None:
    data = {
        **MINIMAL_CONFIG,
        "ev_chargers": [
            {
                "id": "ev1",
                "enabled": True,
                "target_soc_percent": 75,
                "penalty_levels": [{"max_soc": 100, "penalty_sek": 5}],
            }
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        path = f.name
    try:
        _write_config(path, data)
        cfg = load_executor_config(path)
    finally:
        Path(path).unlink(missing_ok=True)

    assert cfg.ev_chargers[0].target_soc_percent == 75


def test_repeat_modes() -> None:
    data = {
        **MINIMAL_CONFIG,
        "ev_chargers": [
            {"id": "ev1", "enabled": True, "repeat": "weekdays"},
            {"id": "ev2", "enabled": True, "repeat": "every_n_days", "n_days": 3},
            {"id": "ev3", "enabled": True, "repeat": "none", "ready_by_date": "2026-06-12"},
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        path = f.name
    try:
        _write_config(path, data)
        cfg = load_executor_config(path)
    finally:
        Path(path).unlink(missing_ok=True)

    assert cfg.ev_chargers[0].repeat == EVRepeatMode.WEEKDAYS
    assert cfg.ev_chargers[1].repeat == EVRepeatMode.EVERY_N_DAYS
    assert cfg.ev_chargers[1].n_days == 3
    assert cfg.ev_chargers[2].repeat == EVRepeatMode.NONE
    assert cfg.ev_chargers[2].ready_by_date == "2026-06-12"


def test_invalid_repeat_defaults_to_daily() -> None:
    data = {
        **MINIMAL_CONFIG,
        "ev_chargers": [
            {"id": "ev1", "enabled": True, "repeat": "fortnightly"},
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        path = f.name
    try:
        _write_config(path, data)
        cfg = load_executor_config(path)
    finally:
        Path(path).unlink(missing_ok=True)

    assert cfg.ev_chargers[0].repeat == EVRepeatMode.DAILY


def test_invalid_ready_by_falls_back_to_default() -> None:
    data = {
        **MINIMAL_CONFIG,
        "ev_chargers": [
            {"id": "ev1", "enabled": True, "ready_by": "25:00"},
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        path = f.name
    try:
        _write_config(path, data)
        cfg = load_executor_config(path)
    finally:
        Path(path).unlink(missing_ok=True)

    # Invalid time is rejected and the shipped default is used.
    assert cfg.ev_chargers[0].ready_by == "07:00"
