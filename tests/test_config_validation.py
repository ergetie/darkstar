from backend.api.routers.config import _validate_config_for_save


def test_validate_config_executor_entities_required_when_enabled():
    config = {
        "executor": {"enabled": True, "inverter": {}},
        "system": {"has_battery": True},
        "input_sensors": {},
    }
    issues = _validate_config_for_save(config)

    # Should have errors for missing critical entities
    error_messages = [i["message"] for i in issues if i["severity"] == "error"]
    assert any("executor.inverter.work_mode_entity" in m for m in error_messages)
    assert any("executor.inverter.grid_charging_entity" in m for m in error_messages)
    assert any("input_sensors.battery_soc" in m for m in error_messages)


def test_validate_config_executor_entities_not_required_when_disabled():
    config = {
        "executor": {"enabled": False, "inverter": {}},
        "system": {"has_battery": True},
        "input_sensors": {},
    }
    issues = _validate_config_for_save(config)

    # Should NOT have errors for missing executor entities if disabled
    # (But might still have battery capacity error if has_battery is True)
    error_messages = [i["message"] for i in issues if i["severity"] == "error"]
    assert not any("executor.inverter.work_mode_entity" in m for m in error_messages)
    assert not any("executor.inverter.grid_charging_entity" in m for m in error_messages)
    # input_sensors.battery_soc might still be considered critical for other things?
    # Current implementation in _validate_config_for_save only checks them if executor is enabled.
    assert not any("input_sensors.battery_soc" in m for m in error_messages)


def test_validate_config_battery_capacity_required():
    config = {
        "executor": {"enabled": False},
        "system": {"has_battery": True},
        "battery": {"capacity_kwh": 0},
    }
    issues = _validate_config_for_save(config)
    assert any(
        "Battery enabled but capacity not configured" in i["message"]
        for i in issues
        if i["severity"] == "error"
    )


def test_validate_config_valid_config_no_issues():
    config = {
        "executor": {
            "enabled": True,
            "inverter": {
                "work_mode_entity": "select.inverter_work_mode",
                "grid_charging_entity": "switch.inverter_grid_charging",
            },
        },
        "system": {"has_battery": True},
        "battery": {"capacity_kwh": 10.0},
        "input_sensors": {"battery_soc": "sensor.battery_soc"},
    }
    issues = _validate_config_for_save(config)
    errors = [i for i in issues if i["severity"] == "error"]
    assert len(errors) == 0
