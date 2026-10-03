"""Declarative role rules shared by discovery suggestions and readiness."""

from typing import Any

POWER_UNITS = ["W", "kW"]
ROLE_RULES: dict[str, dict[str, Any]] = {
    "battery_soc": {
        "domain": ["sensor"],
        "device_class": ["battery"],
        "unit": ["%"],
        "entity_id_regex": r"battery.*(soc|charge)|state_of_charge",
        "name_regex": r"battery|state.of.charge",
    },
}
for _role in (
    "pv_power",
    "load_power",
    "battery_power",
    "grid_power",
    "grid_import_power",
    "grid_export_power",
):
    _prefix = {
        "pv_power": r"pv|solar",
        "load_power": r"load|consumption",
        "battery_power": "battery",
        "grid_import_power": r"grid.*import|import.*power",
        "grid_export_power": r"grid.*export|export.*power",
        "grid_power": "grid",
    }[_role]
    ROLE_RULES[_role] = {
        "domain": ["sensor"],
        "device_class": ["power"],
        "unit": POWER_UNITS,
        "entity_id_regex": _prefix,
        "name_regex": _prefix,
    }
ROLE_RULES.update(
    {
        "water_heater_control": {
            "domain": ["switch", "input_boolean", "number", "input_number"],
            "entity_id_regex": r"water|boiler|heater",
            "name_regex": r"water|boiler|heater",
        },
        "water_heater_power": {
            "domain": ["sensor"],
            "device_class": ["power"],
            "unit": POWER_UNITS,
            "entity_id_regex": r"water|boiler|heater",
            "name_regex": r"water|boiler|heater",
        },
        "ev_switch": {
            "domain": ["switch", "input_boolean", "select", "input_select"],
            "entity_id_regex": r"ev|charg|wallbox",
            "name_regex": r"ev|charg|wallbox",
        },
        "ev_current": {
            "domain": ["number", "input_number"],
            "device_class": ["current"],
            "unit": ["A"],
            "entity_id_regex": r"current|amp",
            "name_regex": r"current|amp",
        },
        "ev_soc": {
            "domain": ["sensor"],
            "device_class": ["battery"],
            "unit": ["%"],
            "entity_id_regex": r"ev|car|vehicle|soc",
            "name_regex": r"ev|car|vehicle|charge",
        },
        "ev_plug": {
            "domain": ["binary_sensor"],
            "device_class": ["plug", "connectivity"],
            "entity_id_regex": r"plug|connect",
            "name_regex": r"plug|connect",
        },
        "ev_power": {
            "domain": ["sensor"],
            "device_class": ["power"],
            "unit": POWER_UNITS,
            "entity_id_regex": r"ev|charg|wallbox",
            "name_regex": r"ev|charg|wallbox",
        },
    }
)
ROLE_PATHS = {
    role: f"input_sensors.{role}"
    for role in ROLE_RULES
    if not role.startswith(("ev_", "water_heater_"))
}
ROLE_PATHS.update(
    {
        "water_heater_control": "water_heaters.0.target_entity",
        "water_heater_power": "water_heaters.0.sensor",
        "ev_switch": "ev_chargers.0.switch_entity",
        "ev_current": "ev_chargers.0.current_entity",
        "ev_soc": "ev_chargers.0.soc_sensor",
        "ev_plug": "ev_chargers.0.plug_sensor",
        "ev_power": "ev_chargers.0.sensor",
    }
)
