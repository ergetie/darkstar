"""With system.has_water_heater false, stale heater values raise no water issues."""

import pytest
import yaml

from backend.api.routers.config import _validate_config_for_save
from backend.health import HealthChecker

STALE_HEATER = {
    "id": "main_tank",
    "enabled": True,
    "power_kw": 0,
    "sensor": "",
    "target_entity": "switch.vvb",
    "control_type": "temperature",
    "max_hours_between_heating": -1,
}


def _water_issues(issues, key):
    return [i for i in issues if "water" in str(i[key]).lower()]


@pytest.mark.parametrize("flag", [False, True])
def test_config_save_validation_follows_flag(flag):
    config = {
        "config_version": 2,
        "system": {"has_water_heater": flag},
        "water_heating": {"defer_up_to_hours": 99},
        "water_heaters": [STALE_HEATER],
    }
    issues = _water_issues(_validate_config_for_save(config, {}), "message")
    assert bool(issues) is flag


@pytest.mark.parametrize("flag", [False, True])
def test_health_config_check_follows_flag(tmp_path, flag):
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {"system": {"has_water_heater": flag}, "water_heaters": [STALE_HEATER]}
        )
    )
    issues = [i.to_dict() for i in HealthChecker(str(path)).check_config_validity()]
    assert bool(_water_issues(issues, "message")) is flag
