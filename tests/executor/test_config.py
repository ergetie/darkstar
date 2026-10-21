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


class TestControllerMinSoc:
    """min-soc-floor-tracking D2: battery.min_soc_percent reaches ControllerConfig."""

    def _load(self, tmp_path, data):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(data))
        return load_executor_config(str(config_file)).controller

    def test_min_soc_read_from_battery_section(self, tmp_path):
        ctrl = self._load(tmp_path, {"battery": {"min_soc_percent": 12}, "executor": {"enabled": True}})
        assert ctrl.min_soc_percent == 12.0

    def test_missing_min_soc_defaults_to_planner_fallback(self, tmp_path):
        ctrl = self._load(tmp_path, {"battery": {"capacity_kwh": 19.2}, "executor": {"enabled": True}})
        assert ctrl.min_soc_percent == 10.0

    def test_zero_min_soc_is_kept(self, tmp_path):
        ctrl = self._load(tmp_path, {"battery": {"min_soc_percent": 0}, "executor": {"enabled": True}})
        assert ctrl.min_soc_percent == 0.0

    def test_min_soc_read_without_executor_section(self, tmp_path):
        ctrl = self._load(tmp_path, {"battery": {"min_soc_percent": 12}})
        assert ctrl.min_soc_percent == 12.0

    def test_min_soc_read_with_empty_executor_section(self, tmp_path):
        ctrl = self._load(tmp_path, {"battery": {"min_soc_percent": 12}, "executor": {}})
        assert ctrl.min_soc_percent == 12.0


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
                    "target_entity": "input_number.water_heater_1",
                    "power_kw": 3.0,
                },
                {
                    "id": "wh2",
                    "name": "Cabin Heater",
                    "enabled": True,
                    "target_entity": "input_number.water_heater_2",
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
        assert wh1.target_entity == "input_number.water_heater_1"
        assert wh1.power_kw == 3.0

        wh2 = config.water_heater_devices[1]
        assert wh2.id == "wh2"
        assert wh2.target_entity == "input_number.water_heater_2"
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
                    "target_entity": "input_number.water_heater_1",
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

    def test_control_type_switch_loads_as_switch(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.safe_dump(
                {
                    "executor": {"enabled": True},
                    "water_heaters": [
                        {
                            "id": "relay",
                            "target_entity": "switch.vvb",
                            "control_type": " SWITCH ",
                        }
                    ],
                }
            )
        )

        config = load_executor_config(str(config_file))

        assert config.water_heater_devices[0].control_type == "switch"

    def test_control_type_defaults_to_temperature_and_ignores_load_type(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.safe_dump(
                {
                    "executor": {"enabled": True},
                    "water_heaters": [
                        {
                            "id": "temperature",
                            "target_entity": "input_number.vvbtemp",
                            "type": "binary",
                        }
                    ],
                }
            )
        )

        config = load_executor_config(str(config_file))

        assert config.water_heater_devices[0].control_type == "temperature"

    def test_missing_control_type_is_inferred_from_entity_domain(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.safe_dump(
                {
                    "executor": {"enabled": True},
                    "water_heaters": [{"id": "relay", "target_entity": "switch.vvb"}],
                }
            )
        )

        config = load_executor_config(str(config_file))

        assert config.water_heater_devices[0].control_type == "switch"

    def test_unrecognised_control_type_falls_back_to_temperature(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.safe_dump(
                {
                    "executor": {"enabled": True},
                    "water_heaters": [
                        {
                            "id": "temperature",
                            "target_entity": "number.vvbtemp",
                            "control_type": "relay",
                        }
                    ],
                }
            )
        )

        config = load_executor_config(str(config_file))

        assert config.water_heater_devices[0].control_type == "temperature"

    def test_mismatched_control_type_is_skipped_and_warned(self, tmp_path, caplog):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.safe_dump(
                {
                    "executor": {"enabled": True},
                    "water_heaters": [
                        {
                            "id": "bad_relay",
                            "target_entity": "number.vvbtemp",
                            "control_type": "switch",
                        },
                        {
                            "id": "good_relay",
                            "target_entity": "switch.vvb",
                            "control_type": "switch",
                        },
                    ],
                }
            )
        )

        with caplog.at_level("WARNING"):
            config = load_executor_config(str(config_file))

        assert [heater.id for heater in config.water_heater_devices] == ["good_relay"]
        assert "bad_relay" in caplog.text

    def test_mixed_control_types_load_independently(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.safe_dump(
                {
                    "executor": {"enabled": True},
                    "water_heaters": [
                        {"id": "relay", "target_entity": "switch.vvb", "control_type": "switch"},
                        {"id": "temperature", "target_entity": "number.vvbtemp"},
                    ],
                }
            )
        )

        config = load_executor_config(str(config_file))

        assert [(heater.id, heater.control_type) for heater in config.water_heater_devices] == [
            ("relay", "switch"),
            ("temperature", "temperature"),
        ]

    def test_disabled_heater_excluded(self, tmp_path):
        """Disabled heaters are not included in water_heater_devices."""
        config_file = tmp_path / "config.yaml"
        config_data = {
            "executor": {"enabled": True},
            "water_heaters": [
                {
                    "id": "wh1",
                    "enabled": True,
                    "target_entity": "input_number.water_heater_1",
                    "power_kw": 3.0,
                },
                {
                    "id": "wh2",
                    "enabled": False,
                    "target_entity": "input_number.water_heater_2",
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
                    "target_entity": "input_number.water_heater_1",
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


class TestEVChargerPhaseSwitchingConfig:
    """excess-pv-priority-dispatch 1.2: phase-switching fields on ev_chargers[]."""

    def test_phase_switching_fields_round_trip(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_data = {
            "executor": {"enabled": True},
            "ev_chargers": [
                {
                    "id": "goe",
                    "enabled": True,
                    "type": "current",
                    "phase_mode_entity": "select.goe_phase_mode",
                    "phase_switching_enabled": True,
                    "phase_switch_hysteresis_kw": 0.3,
                    "phase_switch_min_dwell_s": 300,
                }
            ],
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = load_executor_config(str(config_file))

        ev = config.ev_chargers[0]
        assert ev.phase_mode_entity == "select.goe_phase_mode"
        assert ev.phase_switching_enabled is True
        assert ev.phase_switch_hysteresis_kw == 0.3
        assert ev.phase_switch_min_dwell_s == 300

    def test_phase_switching_defaults_when_absent(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_data = {
            "executor": {"enabled": True},
            "ev_chargers": [{"id": "leaf", "enabled": True, "switch_entity": "switch.leaf"}],
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = load_executor_config(str(config_file))

        ev = config.ev_chargers[0]
        assert ev.phase_mode_entity is None
        assert ev.phase_switching_enabled is False
        assert ev.phase_switch_hysteresis_kw == 0.5
        assert ev.phase_switch_min_dwell_s == 600


class TestExcessPvPriorityConfig:
    """excess-pv-priority-dispatch 1.1: executor.excess_pv.priority[] parsing."""

    def test_full_priority_list_all_entry_types(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_data = {
            "executor": {
                "enabled": True,
                "excess_pv": {
                    "priority": [
                        {
                            "type": "ev",
                            "charger_id": "goe",
                            "surplus_deadband_kw": 0.3,
                            "reward_sek_per_kwh": 0.6,
                        },
                        {"type": "water_heater_boost"},
                        {
                            "type": "custom_entity",
                            "entity": "switch.pool_pump",
                            "on_value": "on",
                            "off_value": "off",
                            "power_kw": 2.5,
                        },
                    ],
                    "boost_reward_sek_per_kwh": 0.5,
                    "soc_threshold_percent": 90,
                },
            }
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = load_executor_config(str(config_file))

        excess_pv = config.excess_pv
        assert excess_pv.boost_reward_sek_per_kwh == 0.5
        assert excess_pv.soc_threshold_percent == 90
        assert len(excess_pv.priority) == 3

        ev_entry = excess_pv.priority[0]
        assert ev_entry.type == "ev"
        assert ev_entry.charger_id == "goe"
        assert ev_entry.surplus_deadband_kw == 0.3
        assert ev_entry.reward_sek_per_kwh == 0.6

        boost_entry = excess_pv.priority[1]
        assert boost_entry.type == "water_heater_boost"
        assert boost_entry.reward_sek_per_kwh is None

        custom_entry = excess_pv.priority[2]
        assert custom_entry.type == "custom_entity"
        assert custom_entry.entity == "switch.pool_pump"
        assert custom_entry.on_value == "on"
        assert custom_entry.off_value == "off"
        assert custom_entry.power_kw == 2.5

    def test_defaults_when_priority_absent(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        with config_file.open("w") as f:
            yaml.dump({"executor": {}}, f)

        config = load_executor_config(str(config_file))

        assert config.excess_pv.priority == []
        assert config.excess_pv.boost_reward_sek_per_kwh == 0.5
        assert config.excess_pv.soc_threshold_percent == 95.0

    def test_unknown_entry_type_ignored(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_data = {
            "executor": {
                "excess_pv": {
                    "priority": [
                        {"type": "water_heater_boost"},
                        {"type": "some_future_sink"},
                    ]
                }
            }
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = load_executor_config(str(config_file))

        assert len(config.excess_pv.priority) == 1
        assert config.excess_pv.priority[0].type == "water_heater_boost"

    def test_surplus_deadband_default(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_data = {
            "executor": {
                "excess_pv": {"priority": [{"type": "ev", "charger_id": "goe"}]}
            }
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = load_executor_config(str(config_file))

        assert config.excess_pv.priority[0].surplus_deadband_kw == 0.2


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
        assert lb.target_margin_percent == 85.0
        assert lb.ramp_up_window_s == 60
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
        # A user-tuned legacy resume_margin_percent carries over.
        assert lb.target_margin_percent == 85.0
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

        # User-specified order is preserved on load; the battery entry is
        # self-healed onto the end (generic profile has a charge mode).
        assert [(e.kind, e.id) for e in lb.give_way_order] == [
            ("shed", "pool_pump"),
            ("shed", "main_tank"),
            ("battery", "battery"),
        ]

    def _load_order(self, tmp_path, give_way_order, system=None):
        config_file = tmp_path / "config.yaml"
        config_data = {
            "executor": {"enabled": True},
            "system": system or {"inverter_profile": "deye"},
            "ev_chargers": [{"id": "main_ev", "type": "current", "enabled": True}],
            "load_balancing": {
                "loads": [{"device_type": "water_heater", "device_id": "main_tank", "phases": [2]}],
                "give_way_order": give_way_order,
            },
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)
        lb = load_executor_config(str(config_file)).load_balancing
        return [(e.kind, e.id) for e in lb.give_way_order]

    def test_battery_entry_parsed_at_position(self, tmp_path):
        """battery-load-balancing 1.1: battery kept between a charger and a shed load."""
        order = self._load_order(
            tmp_path,
            [
                {"kind": "charger", "id": "main_ev"},
                {"kind": "battery", "id": "battery"},
                {"kind": "shed", "id": "main_tank"},
            ],
        )
        assert order == [("charger", "main_ev"), ("battery", "battery"), ("shed", "main_tank")]

    def test_battery_id_normalised_and_duplicates_dropped(self, tmp_path):
        order = self._load_order(
            tmp_path,
            [
                {"kind": "battery", "id": "house"},
                {"kind": "charger", "id": "main_ev"},
                {"kind": "battery"},
                {"kind": "shed", "id": "main_tank"},
            ],
        )
        assert order == [("battery", "battery"), ("charger", "main_ev"), ("shed", "main_tank")]

    def test_battery_appended_at_end_for_existing_users(self, tmp_path):
        """battery-load-balancing 1.2: upgrade with a Deye profile appends the battery last."""
        order = self._load_order(
            tmp_path,
            [{"kind": "charger", "id": "main_ev"}, {"kind": "shed", "id": "main_tank"}],
        )
        assert order == [("charger", "main_ev"), ("shed", "main_tank"), ("battery", "battery")]

    def test_battery_dropped_without_battery(self, tmp_path):
        order = self._load_order(
            tmp_path,
            [{"kind": "battery", "id": "battery"}, {"kind": "charger", "id": "main_ev"}],
            system={"inverter_profile": "deye", "has_battery": False},
        )
        assert order == [("charger", "main_ev"), ("shed", "main_tank")]


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


class TestHealGiveWayOrderBattery:
    """battery-load-balancing 1.2: heal_give_way_order battery rules."""

    def _lb(self, entries):
        from executor.config import GiveWayOrderEntry, LoadBalancingConfig

        return LoadBalancingConfig(
            give_way_order=[GiveWayOrderEntry(kind=k, id=i) for k, i in entries]
        )

    def test_dropped_when_no_controllable_battery(self):
        from executor.config import heal_give_way_order

        lb = self._lb([("battery", "battery"), ("charger", "ev")])
        heal_give_way_order(lb, ["ev"], battery_available=False)
        assert [(e.kind, e.id) for e in lb.give_way_order] == [("charger", "ev")]

    def test_kept_in_place_and_deduplicated(self):
        from executor.config import heal_give_way_order

        lb = self._lb([("battery", "battery"), ("charger", "ev"), ("battery", "battery")])
        heal_give_way_order(lb, ["ev"], battery_available=True)
        assert [(e.kind, e.id) for e in lb.give_way_order] == [
            ("battery", "battery"),
            ("charger", "ev"),
        ]

    def test_appended_after_missing_chargers_and_loads(self):
        from executor.config import (
            BalancedLoadConfig,
            heal_give_way_order,
        )

        lb = self._lb([])
        lb.loads = [BalancedLoadConfig(device_id="tank", phases=[1])]
        heal_give_way_order(lb, ["ev"], battery_available=True)
        assert [(e.kind, e.id) for e in lb.give_way_order] == [
            ("charger", "ev"),
            ("shed", "tank"),
            ("battery", "battery"),
        ]

    def test_battery_available_requires_charge_mode_profile(self):
        from executor.config import battery_give_way_available

        assert battery_give_way_available({"system": {"inverter_profile": "deye"}}) is True
        assert battery_give_way_available({"system": {"has_battery": False}}) is False

    def test_battery_available_false_when_profile_fails(self, monkeypatch):
        import executor.config as cfg

        def boom(_data):
            raise RuntimeError("broken")

        monkeypatch.setattr(cfg, "get_profile_from_config", boom)
        assert cfg.battery_give_way_available({"system": {}}) is False


def test_soc_deviation_replan_percent_default_and_override(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({"executor": {}}))
    assert load_executor_config(str(config_file)).soc_deviation_replan_percent == 10.0

    config_file.write_text(yaml.dump({"executor": {"soc_deviation_replan_percent": 15}}))
    assert load_executor_config(str(config_file)).soc_deviation_replan_percent == 15.0

    config_file.write_text(yaml.dump({"executor": {"soc_deviation_replan_percent": 0}}))
    assert load_executor_config(str(config_file)).soc_deviation_replan_percent == 0.0


def test_soc_deviation_replan_percent_out_of_range_uses_default(tmp_path):
    config_file = tmp_path / "config.yaml"
    for bad in (-1, 51, "abc"):
        config_file.write_text(yaml.dump({"executor": {"soc_deviation_replan_percent": bad}}))
        assert load_executor_config(str(config_file)).soc_deviation_replan_percent == 10.0
