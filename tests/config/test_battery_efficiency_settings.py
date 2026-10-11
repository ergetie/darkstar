"""Battery efficiency settings stay physically valid and use fractional config units."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.api.routers import config


@pytest.mark.parametrize("key", ["charge_efficiency", "discharge_efficiency"])
@pytest.mark.parametrize("value", [0.0001, 0.92, 0.95, 1.0])
def test_valid_efficiency(key, value):
    issues = config._validate_config_for_save({"battery": {key: value}})
    assert not [issue for issue in issues if issue.get("field") == f"battery.{key}"]


@pytest.mark.parametrize("key", ["charge_efficiency", "discharge_efficiency"])
@pytest.mark.parametrize(
    "value",
    [None, True, False, "bad", 0, -0.01, 1.05, 92, float("nan"), float("inf"), -float("inf")],
)
def test_invalid_efficiency(key, value):
    issues = config._validate_config_for_save({"battery": {key: value}})
    errors = [issue for issue in issues if issue.get("field") == f"battery.{key}"]
    assert len(errors) == 1
    assert errors[0]["severity"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, True, 0, 1.05, "Infinity"])
async def test_invalid_api_save_preserves_config(value, tmp_path, monkeypatch):
    defaults = Path("config.default.yaml").read_text()
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(defaults)
    (tmp_path / "config.default.yaml").write_text(defaults)
    monkeypatch.setattr(config, "_phase_sensor_units_for_config", AsyncMock(return_value={}))

    with pytest.raises(HTTPException) as error:
        await config.save_config({"battery": {"charge_efficiency": value}})

    assert error.value.status_code == 400
    assert any(
        issue.get("field") == "battery.charge_efficiency" for issue in error.value.detail["errors"]
    )
    assert config_path.read_text() == defaults
