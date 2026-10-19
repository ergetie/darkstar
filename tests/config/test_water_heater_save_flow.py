"""End-to-end save flow for the water heater control-type backlog bug (no trap)."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from ruamel.yaml import YAML

from backend.api.routers import config

HEATER = {"id": "tank", "name": "Tank", "power_kw": 3.0, "enabled": True}


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    defaults = Path("config.default.yaml").read_text()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.default.yaml").write_text(defaults)
    path = tmp_path / "config.yaml"
    path.write_text(defaults)
    monkeypatch.setattr(config, "_phase_sensor_units_for_config", AsyncMock(return_value={}))
    return path


def _seed(path, heaters):
    yaml = YAML()
    data = yaml.load(path.read_text())
    data["system"]["has_water_heater"] = True
    data["water_heaters"] = heaters
    with path.open("w") as handle:
        yaml.dump(data, handle)


def _saved(path):
    return YAML().load(path.read_text())


@pytest.mark.asyncio
async def test_prod_like_switch_heater_without_control_type_saves(cfg_path):
    _seed(cfg_path, [{**HEATER, "target_entity": "switch.vvb"}])
    # Saving another tab, then the heater itself (toggled off/on), both succeed.
    await config.save_config({"battery": {"capacity_kwh": 12.0}})
    assert _saved(cfg_path)["water_heaters"][0]["control_type"] == "switch"
    for enabled in (False, True):
        heater = {**HEATER, "target_entity": "switch.vvb", "enabled": enabled}
        await config.save_config({"water_heaters": [heater]})
        assert _saved(cfg_path)["water_heaters"][0]["control_type"] == "switch"


@pytest.mark.asyncio
async def test_explicit_mismatch_is_rejected_but_never_traps(cfg_path):
    bad = {**HEATER, "target_entity": "switch.vvb", "control_type": "temperature"}
    with pytest.raises(HTTPException) as error:
        await config.save_config({"water_heaters": [bad]})
    assert error.value.status_code == 400
    assert error.value.detail["errors"][0]["field"] == "water_heaters.0.control_type"

    # A stale hand-edited mismatch on disk must not block saves of other tabs.
    _seed(cfg_path, [bad])
    await config.save_config({"battery": {"capacity_kwh": 11.0}})
    # Escape routes: disable the heater, remove it, or turn the feature off.
    await config.save_config({"water_heaters": [{**bad, "enabled": False}]})
    await config.save_config({"water_heaters": []})
    _seed(cfg_path, [bad])
    await config.save_config({"system": {"has_water_heater": False}})
    # Fixing the pair also saves.
    _seed(cfg_path, [bad])
    await config.save_config({"water_heaters": [{**bad, "control_type": "switch"}]})
    assert _saved(cfg_path)["water_heaters"][0]["control_type"] == "switch"
