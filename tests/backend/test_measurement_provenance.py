from backend.measurement_provenance import boundary_fingerprint


def test_battery_soc_mapping_changes_measurement_boundary():
    first = {
        "input_sensors": {"pv_power": "sensor.pv", "battery_soc": "sensor.soc_a"},
        "system": {"has_battery": True},
    }
    second = {
        "input_sensors": {"pv_power": "sensor.pv", "battery_soc": "sensor.soc_b"},
        "system": {"has_battery": True},
    }
    assert boundary_fingerprint(first) != boundary_fingerprint(second)


def test_capacity_and_operational_reserve_are_not_measurement_boundary_inputs():
    first = {
        "system": {"has_battery": True, "battery": {"capacity_kwh": 10, "min_soc_percent": 10}}
    }
    second = {
        "system": {"has_battery": True, "battery": {"capacity_kwh": 20, "min_soc_percent": 20}}
    }
    assert boundary_fingerprint(first) == boundary_fingerprint(second)
