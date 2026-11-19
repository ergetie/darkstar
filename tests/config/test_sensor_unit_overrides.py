"""sensor-unit-overrides: default key, migration, save validation and pruning."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi import HTTPException

from backend.api.routers import config as config_router
from backend.config_migration import _migrate_config

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO_ROOT / "config.default.yaml"


def _issues(overrides):
    return config_router._validate_sensor_unit_overrides(overrides)


def test_default_config_has_empty_overrides():
    assert yaml.safe_load(DEFAULT_PATH.read_text())["sensor_unit_overrides"] == {}


def test_migration_adds_the_key_to_an_old_config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"timezone": "Europe/Stockholm"}), encoding="utf-8")
    _migrate_config(str(path), str(DEFAULT_PATH), False)
    assert yaml.safe_load(path.read_text())["sensor_unit_overrides"] == {}


@pytest.mark.parametrize("overrides", [None, {}, {"sensor.x": "W"}, {"sensor.x_1": "kW"}])
def test_valid_overrides_are_accepted(overrides):
    assert _issues(overrides) == []


@pytest.mark.parametrize(
    ("overrides", "named"),
    [
        ({"sensor.x": "MW"}, "sensor.x"),
        ({"sensor.x": "w"}, "sensor.x"),
        ({"sensor.x": None}, "sensor.x"),
        ({"not an entity": "W"}, "not an entity"),
        ({"Sensor.X": "W"}, "Sensor.X"),
        ({"sensor": "W"}, "sensor"),
        ("W", "sensor_unit_overrides"),
    ],
)
def test_invalid_overrides_are_rejected_naming_the_entry(overrides, named):
    issues = _issues(overrides)
    assert len(issues) == 1
    assert issues[0]["severity"] == "error"
    assert named in issues[0]["message"]


def test_full_validation_reports_invalid_override():
    cfg = yaml.safe_load(DEFAULT_PATH.read_text())
    cfg["sensor_unit_overrides"] = {"sensor.x": "MW"}
    errors = [
        i
        for i in config_router._validate_config_for_save(cfg, {})
        if i["severity"] == "error" and "sensor_unit_overrides" in i["message"]
    ]
    assert len(errors) == 1


def test_prune_keeps_referenced_and_drops_stale():
    cfg = {
        "system": {"has_ev_charger": False},
        "input_sensors": {"pv_power": "sensor.pv"},
        "ev_chargers": [{"enabled": False, "sensor": "sensor.ev"}],
        "sensor_unit_overrides": {
            "sensor.pv": "W",
            "sensor.ev": "kW",  # configured but its feature is off: kept
            "sensor.gone": "W",
        },
    }
    dropped = config_router._prune_sensor_unit_overrides(cfg)
    assert dropped == ["sensor.gone"]
    assert cfg["sensor_unit_overrides"] == {"sensor.pv": "W", "sensor.ev": "kW"}


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    defaults = DEFAULT_PATH.read_text()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.default.yaml").write_text(defaults)
    path = tmp_path / "config.yaml"
    path.write_text(defaults)
    monkeypatch.setattr(config_router, "_phase_sensor_units_for_config", AsyncMock(return_value={}))
    return path


def _saved(path):
    return yaml.safe_load(path.read_text())


@pytest.mark.asyncio
async def test_save_prunes_stale_overrides_and_keeps_referenced(cfg_path):
    await config_router.save_config(
        {
            "input_sensors": {"pv_power": "sensor.pv", "load_power": "sensor.load"},
            "sensor_unit_overrides": {"sensor.pv": "W", "sensor.old": "W"},
        }
    )
    assert _saved(cfg_path)["sensor_unit_overrides"] == {"sensor.pv": "W"}

    # Selecting a different sensor drops the override of the one no longer referenced.
    await config_router.save_config({"input_sensors": {"pv_power": "sensor.pv2"}})
    assert _saved(cfg_path)["sensor_unit_overrides"] == {}


@pytest.mark.asyncio
async def test_save_rejects_invalid_override_without_writing(cfg_path):
    before = cfg_path.read_text()
    with pytest.raises(HTTPException) as error:
        await config_router.save_config(
            {
                "input_sensors": {"pv_power": "sensor.pv"},
                "sensor_unit_overrides": {"sensor.pv": "MW"},
            }
        )
    assert error.value.status_code == 400
    assert "sensor.pv" in error.value.detail["errors"][0]["message"]
    assert cfg_path.read_text() == before
