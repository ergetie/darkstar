import yaml

from executor.config import _str_or_none, load_executor_config


def test_str_or_none_normalization():
    """Verify that _str_or_none correctly normalizes various input types."""
    assert _str_or_none("sensor.test") == "sensor.test"
    assert _str_or_none("") is None
    assert _str_or_none(" ") is None
    assert _str_or_none(None) is None
    assert _str_or_none(123) == "123"
    assert _str_or_none("\t\n") is None


def test_load_executor_config_normalization(tmp_path):
    """Verify that load_executor_config correctly applies normalization to entity fields."""
    config_file = tmp_path / "config.yaml"

    # Create a config with various empty/none/valid entities
    config_data = {
        "executor": {
            "inverter": {
                "work_mode_entity": "select.my_mode",
                "grid_charging_entity": "",
                "max_charging_current_entity": "  ",
                "max_discharging_current_entity": None,
            },
            "water_heater": {"target_entity": ""},
            "soc_target_entity": "input_number.target",
        }
    }

    with config_file.open("w") as f:
        yaml.dump(config_data, f)

    config = load_executor_config(str(config_file))

    # Assert normalized values
    assert config.inverter.work_mode_entity == "select.my_mode"
    assert config.inverter.grid_charging_entity is None
    assert config.inverter.max_charging_current_entity is None
    assert config.inverter.max_discharging_current_entity is None
    assert config.water_heater.target_entity is None
    assert config.soc_target_entity == "input_number.target"

    # Assert other default values stay valid
    assert config.inverter.work_mode_export == "Export First"
    assert config.water_heater.temp_normal == 60


def test_load_executor_config_defaults(tmp_path):
    """Verify that missing entities default to None in the loaded config."""
    config_file = tmp_path / "config.yaml"
    config_data = {"executor": {}}

    with config_file.open("w") as f:
        yaml.dump(config_data, f)

    config = load_executor_config(str(config_file))

    assert config.inverter.work_mode_entity is None
    assert config.inverter.grid_charging_entity is None
    assert config.water_heater.target_entity is None
    assert config.automation_toggle_entity is None
