"""fix-ev-current-charger-control 2.1: type=current chargers require switch_entity."""

from executor.config import EVChargerDeviceConfig, ExecutorConfig, validate_ev_chargers


def _config(**charger_overrides) -> ExecutorConfig:
    params = {
        "id": "goe",
        "type": "current",
        "current_entity": "number.goe_current",
        "switch_entity": "select.goe_frc",
        "charge_enabled_value": "charge",
        "charge_disabled_value": "dont_charge",
    }
    params.update(charger_overrides)
    return ExecutorConfig(ev_chargers=[EVChargerDeviceConfig(**params)])


def test_valid_current_charger_has_no_errors():
    assert validate_ev_chargers(_config()) == []


def test_missing_switch_entity_names_charger():
    errors = validate_ev_chargers(_config(switch_entity=""))
    assert len(errors) == 1
    assert "'goe'" in errors[0]
    assert "switch_entity" in errors[0]


def test_select_values_must_differ():
    errors = validate_ev_chargers(_config(charge_disabled_value="charge"))
    assert len(errors) == 1
    assert "must differ" in errors[0]


def test_switch_like_entity_ignores_select_values():
    assert validate_ev_chargers(_config(switch_entity="switch.goe", charge_enabled_value="")) == []


def test_binary_charger_not_checked():
    assert validate_ev_chargers(_config(type="binary", switch_entity=None)) == []
