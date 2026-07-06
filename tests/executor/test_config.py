import yaml

from executor.config import BalancedLoadType, load_executor_config


def test_nested_custom_entities_loads_correctly(tmp_path):
    """Verify that nested custom_entities in YAML is properly unpacked, not stringified (REV F71)."""
    config_file = tmp_path / "config.yaml"

    config_data = {
        "executor": {
            "inverter": {
                "work_mode": "select.ems_mode",
                "custom_entities": {
                    "ems_mode": "select.ems_mode",
                    "forced_charge_discharge_cmd": "select.battery_forced_charge_discharge",
                },
            }
        }
    }

    with config_file.open("w") as f:
        yaml.dump(config_data, f)

    config = load_executor_config(str(config_file))

    assert config.inverter.custom_entities.get("ems_mode") == "select.ems_mode"
    assert (
        config.inverter.custom_entities.get("forced_charge_discharge_cmd")
        == "select.battery_forced_charge_discharge"
    )


def test_nested_custom_entities_with_legacy_keys(tmp_path):
    """Verify that legacy keys at root level are also captured (REV F69 migration path)."""
    config_file = tmp_path / "config.yaml"

    config_data = {
        "executor": {
            "inverter": {
                "work_mode": "select.ems_mode",
                "ems_mode": "select.ems_mode",
                "forced_charge_discharge_cmd": "select.battery_forced_charge_discharge",
            }
        }
    }

    with config_file.open("w") as f:
        yaml.dump(config_data, f)

    config = load_executor_config(str(config_file))

    assert config.inverter.custom_entities.get("ems_mode") == "select.ems_mode"
    assert (
        config.inverter.custom_entities.get("forced_charge_discharge_cmd")
        == "select.battery_forced_charge_discharge"
    )


def test_custom_entities_not_stringified(tmp_path):
    """Verify that nested dict doesn't get converted to string representation (REV F71)."""
    config_file = tmp_path / "config.yaml"

    config_data = {
        "executor": {
            "inverter": {
                "custom_entities": {
                    "ems_mode": "select.ems_mode",
                }
            }
        }
    }

    with config_file.open("w") as f:
        yaml.dump(config_data, f)

    config = load_executor_config(str(config_file))

    # The value should NOT be a stringified dict representation
    val = config.inverter.custom_entities.get("ems_mode")
    assert val is not None
    assert isinstance(val, str), f"Expected str, got {type(val)}: {val}"
    assert val == "select.ems_mode"


def test_load_executor_config_defaults(tmp_path):
    """Verify that missing entities default to None in the loaded config."""
    config_file = tmp_path / "config.yaml"
    config_data = {"executor": {}}

    with config_file.open("w") as f:
        yaml.dump(config_data, f)

    config = load_executor_config(str(config_file))

    assert config.inverter.work_mode is None
    assert config.inverter.grid_charging_enable is None
    assert config.water_heater.temp_normal == 60
    assert config.automation_toggle_entity is None


class TestWaterHeaterDeviceConfig:
    """Task 5.4: per-device water heater config loading."""

    def test_per_device_configs_built_from_array(self, tmp_path):
        """water_heater_devices list is populated from water_heaters[] entries."""
        config_file = tmp_path / "config.yaml"
        config_data = {
            "executor": {"enabled": True},  # Required to avoid early return
            "water_heaters": [
                {
                    "id": "wh1",
                    "name": "Main Heater",
                    "enabled": True,
                    "target_entity": "climate.water_heater_1",
                    "power_kw": 3.0,
                },
                {
                    "id": "wh2",
                    "name": "Cabin Heater",
                    "enabled": True,
                    "target_entity": "climate.water_heater_2",
                    "power_kw": 2.0,
                },
            ],
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = load_executor_config(str(config_file))

        assert len(config.water_heater_devices) == 2
        wh1 = config.water_heater_devices[0]
        assert wh1.id == "wh1"
        assert wh1.name == "Main Heater"
        assert wh1.target_entity == "climate.water_heater_1"
        assert wh1.power_kw == 3.0

        wh2 = config.water_heater_devices[1]
        assert wh2.id == "wh2"
        assert wh2.target_entity == "climate.water_heater_2"
        assert wh2.power_kw == 2.0

    def test_heater_without_target_entity_excluded(self, tmp_path):
        """Heaters without target_entity are not included in water_heater_devices."""
        config_file = tmp_path / "config.yaml"
        config_data = {
            "executor": {"enabled": True},
            "water_heaters": [
                {
                    "id": "wh1",
                    "enabled": True,
                    "target_entity": "climate.water_heater_1",
                    "power_kw": 3.0,
                },
                {
                    "id": "wh_no_entity",
                    "enabled": True,
                    # No target_entity
                    "power_kw": 2.0,
                },
            ],
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = load_executor_config(str(config_file))

        assert len(config.water_heater_devices) == 1
        assert config.water_heater_devices[0].id == "wh1"

    def test_disabled_heater_excluded(self, tmp_path):
        """Disabled heaters are not included in water_heater_devices."""
        config_file = tmp_path / "config.yaml"
        config_data = {
            "executor": {"enabled": True},
            "water_heaters": [
                {
                    "id": "wh1",
                    "enabled": True,
                    "target_entity": "climate.water_heater_1",
                    "power_kw": 3.0,
                },
                {
                    "id": "wh2",
                    "enabled": False,
                    "target_entity": "climate.water_heater_2",
                    "power_kw": 2.0,
                },
            ],
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = load_executor_config(str(config_file))

        assert len(config.water_heater_devices) == 1
        assert config.water_heater_devices[0].id == "wh1"

    def test_global_temps_still_loaded(self, tmp_path):
        """Global water heater temperatures are loaded into water_heater field."""
        config_file = tmp_path / "config.yaml"
        config_data = {
            "executor": {
                "water_heater": {
                    "temp_normal": 55,
                    "temp_off": 35,
                    "temp_boost": 70,
                }
            },
            "water_heaters": [
                {
                    "id": "wh1",
                    "enabled": True,
                    "target_entity": "climate.water_heater_1",
                    "power_kw": 3.0,
                }
            ],
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = load_executor_config(str(config_file))

        assert config.water_heater.temp_normal == 55
        assert config.water_heater.temp_off == 35
        assert config.water_heater.temp_boost == 70
        assert len(config.water_heater_devices) == 1

    def test_empty_water_heaters_produces_empty_list(self, tmp_path):
        """No water_heaters array produces empty water_heater_devices list."""
        config_file = tmp_path / "config.yaml"
        config_data = {"executor": {}}
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = load_executor_config(str(config_file))

        assert config.water_heater_devices == []


class TestEVChargerCurrentControlConfig:
    """universal-load-balancing 1.2: current-control fields on ev_chargers[]."""

    def test_current_type_device_round_trips(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_data = {
            "executor": {"enabled": True},
            "ev_chargers": [
                {
                    "id": "goe",
                    "enabled": True,
                    "type": "current",
                    "current_entity": "number.goe_current",
                    "min_current_a": 6,
                    "max_current_a": 16,
                    "phases": [1, 2, 3],
                    "phase_sensor_l1": "sensor.goe_l1",
                    "phase_sensor_l2": "sensor.goe_l2",
                    "phase_sensor_l3": "sensor.goe_l3",
                }
            ],
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = load_executor_config(str(config_file))

        assert len(config.ev_chargers) == 1
        ev = config.ev_chargers[0]
        assert ev.type == "current"
        assert ev.current_entity == "number.goe_current"
        assert ev.min_current_a == 6
        assert ev.max_current_a == 16
        assert ev.phases == [1, 2, 3]
        assert ev.phase_sensor_l1 == "sensor.goe_l1"
        assert ev.phase_sensor_l2 == "sensor.goe_l2"
        assert ev.phase_sensor_l3 == "sensor.goe_l3"

    def test_binary_defaults_when_fields_absent(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_data = {
            "executor": {"enabled": True},
            "ev_chargers": [{"id": "leaf", "enabled": True, "switch_entity": "switch.leaf"}],
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = load_executor_config(str(config_file))

        ev = config.ev_chargers[0]
        assert ev.type == "binary"
        assert ev.current_entity is None
        assert ev.min_current_a == 6
        assert ev.max_current_a is None
        assert ev.phases == [1, 2, 3]


class TestLoadBalancingConfig:
    """universal-load-balancing 1.3: load_balancing: section parsing."""

    def test_defaults_when_section_absent(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        with config_file.open("w") as f:
            yaml.dump({"executor": {}}, f)

        config = load_executor_config(str(config_file))

        lb = config.load_balancing
        assert lb.enabled is False
        assert lb.main_fuse_a is None
        assert lb.resume_delay_s == 120
        assert lb.resume_margin_percent == 90.0
        assert lb.increase_step_a == 1
        assert lb.sensor_stale_after_s == 30
        assert lb.loads == []

    def test_parsed_without_executor_section(self, tmp_path):
        """load_balancing is top-level and must parse even with no executor: section."""
        config_file = tmp_path / "config.yaml"
        with config_file.open("w") as f:
            yaml.dump({"load_balancing": {"enabled": True}}, f)

        config = load_executor_config(str(config_file))

        assert config.load_balancing.enabled is True

    def test_full_section_with_loads(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_data = {
            "executor": {"enabled": True},
            "system": {"grid": {"main_fuse_a": 20}},
            "load_balancing": {
                "enabled": True,
                "resume_delay_s": 90,
                "resume_margin_percent": 85,
                "increase_step_a": 2,
                "sensor_stale_after_s": 15,
                "loads": [
                    {
                        "device_type": "water_heater",
                        "device_id": "main_tank",
                        "phases": [2],
                    },
                    {
                        "device_type": "custom_entity",
                        "device_id": "pool_pump",
                        "phases": [3],
                        "entity": "switch.pool_pump",
                        "on_value": "1",
                        "off_value": "0",
                    },
                ],
                "give_way_order": [
                    {"kind": "shed", "id": "pool_pump"},
                    {"kind": "shed", "id": "main_tank"},
                ],
            },
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = load_executor_config(str(config_file))

        lb = config.load_balancing
        assert lb.enabled is True
        assert lb.main_fuse_a == 20
        assert lb.resume_delay_s == 90
        assert lb.resume_margin_percent == 85.0
        assert lb.increase_step_a == 2
        assert lb.sensor_stale_after_s == 15
        assert len(lb.loads) == 2

        wh_load = lb.loads[0]
        assert wh_load.device_type == BalancedLoadType.WATER_HEATER
        assert wh_load.device_id == "main_tank"
        assert wh_load.phases == [2]

        custom_load = lb.loads[1]
        assert custom_load.device_type == BalancedLoadType.CUSTOM_ENTITY
        assert custom_load.entity == "switch.pool_pump"
        assert custom_load.on_value == "1"
        assert custom_load.off_value == "0"

        # User-specified order is preserved on load (no self-heal changes needed)
        assert [(e.kind, e.id) for e in lb.give_way_order] == [
            ("shed", "pool_pump"),
            ("shed", "main_tank"),
        ]

    def test_unknown_device_type_skipped(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_data = {
            "executor": {"enabled": True},
            "load_balancing": {
                "loads": [{"device_type": "spaceship", "device_id": "x", "phases": [1]}]
            },
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = load_executor_config(str(config_file))

        assert config.load_balancing.loads == []
