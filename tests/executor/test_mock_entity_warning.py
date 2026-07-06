import logging

from executor.config import (
    EVChargerDeviceConfig,
    ExecutorConfig,
    InverterConfig,
    WaterHeaterDeviceConfig,
    check_mock_entities,
)


def _base_config(**overrides):
    return ExecutorConfig(**overrides)


def test_enabled_ev_charger_on_mock_entity_warns(caplog):
    config = _base_config(
        ev_chargers=[
            EVChargerDeviceConfig(id="ev_charger_1", switch_entity="input_boolean.ev_mockup_switch")
        ],
        has_battery=False,
    )

    with caplog.at_level(logging.WARNING):
        warnings = check_mock_entities(config)

    assert len(warnings) == 1
    assert "ev_charger_1" in warnings[0]
    assert "input_boolean.ev_mockup_switch" in warnings[0]


def test_disabled_device_is_absent_and_silent():
    # load_executor_config already filters disabled devices out of the list;
    # a device that never made it into config.ev_chargers produces no warning.
    config = _base_config(ev_chargers=[], has_battery=False)

    warnings = check_mock_entities(config)

    assert warnings == []


def test_enabled_device_on_real_entity_is_silent():
    config = _base_config(
        ev_chargers=[EVChargerDeviceConfig(id="ev_charger_1", switch_entity="switch.real_ev_charger")],
        has_battery=False,
    )

    warnings = check_mock_entities(config)

    assert warnings == []


def test_enabled_water_heater_on_test_entity_warns():
    config = _base_config(
        water_heater_devices=[
            WaterHeaterDeviceConfig(id="wh1", name="Water Heater", target_entity="input_number.test_temp")
        ],
        has_battery=False,
    )

    warnings = check_mock_entities(config)

    assert len(warnings) == 1
    assert "Water Heater" in warnings[0]
    assert "input_number.test_temp" in warnings[0]


def test_enabled_inverter_on_mock_entity_warns():
    config = _base_config(
        has_battery=True,
        inverter=InverterConfig(work_mode="select.mock_ems_mode"),
    )

    warnings = check_mock_entities(config)

    assert len(warnings) == 1
    assert "Inverter" in warnings[0]
    assert "select.mock_ems_mode" in warnings[0]


def test_inverter_check_skipped_when_no_battery():
    config = _base_config(
        has_battery=False,
        inverter=InverterConfig(work_mode="select.mock_ems_mode"),
    )

    warnings = check_mock_entities(config)

    assert warnings == []
