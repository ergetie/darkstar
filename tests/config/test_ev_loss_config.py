"""ev-charging-losses 1.1-1.3: loss setting defaults, validation and parsing."""

from pathlib import Path

import pytest
import yaml

from backend.api.routers.config import _validate_ev_loss_settings
from executor.config import load_executor_config


@pytest.mark.asyncio
async def test_existing_charger_gets_loss_defaults(tmp_path, monkeypatch):
    import backend.config_migration as cm

    monkeypatch.setenv(cm.BACKUP_DIR_ENV, str(tmp_path / "backups"))
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "system": {"system_id": "t", "inverter_profile": "generic"},
                "battery": {},
                "executor": {},
                "input_sensors": {},
                "ev_chargers": [{"id": "ev_charger_1", "charge_efficiency": 0.9}],
            }
        )
    )
    default_path = Path(__file__).resolve().parents[2] / "config.default.yaml"

    await cm.migrate_config(str(config_file), str(default_path), strict_validation=False)

    charger = yaml.safe_load(config_file.read_text())["ev_chargers"][0]
    assert charger["charge_overhead_kw"] == 0.25
    assert charger["start_loss_kwh"] == 0.15
    assert charger["charge_efficiency"] == 0.9  # user value kept
    assert charger["energy_added_sensor"] == ""


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("charge_overhead_kw", 0.0),
        ("charge_overhead_kw", 2.0),
        ("start_loss_kwh", 1.0),
        ("charge_efficiency", 0.5),
        ("charge_efficiency", 1.0),
    ],
)
def test_in_range_accepted(key, value):
    assert _validate_ev_loss_settings({key: value}, "ev") == []


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("charge_overhead_kw", -0.1),
        ("charge_overhead_kw", 2.5),
        ("start_loss_kwh", 1.5),
        ("charge_efficiency", 1.2),
        ("charge_efficiency", 0.4),
        ("charge_efficiency", "high"),
        ("start_loss_kwh", True),
    ],
)
def test_out_of_range_rejected(key, value):
    issues = _validate_ev_loss_settings({key: value}, "ev")
    assert len(issues) == 1
    assert key in issues[0]["message"]


def test_executor_config_parses_loss_fields(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.dump(
            {
                "executor": {"enabled": True},
                "ev_chargers": [
                    {"id": "a", "charge_overhead_kw": 0.3, "energy_added_sensor": "sensor.added"},
                    {"id": "b"},
                ],
            }
        )
    )
    a, b = load_executor_config(str(path)).ev_chargers
    assert a.charge_overhead_kw == 0.3
    assert a.energy_added_sensor == "sensor.added"
    assert (b.charge_overhead_kw, b.start_loss_kwh, b.charge_efficiency) == (0.25, 0.15, 0.95)
    assert b.energy_added_sensor is None
