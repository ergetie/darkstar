"""
Executor Configuration

Loads and validates the executor configuration from config.yaml.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, cast

from ruamel.yaml import YAML

logger = logging.getLogger(__name__)


def _str_or_none(value: Any) -> str | None:
    """Convert config value to str or None. Empty strings become None.

    Used to normalize entity IDs from YAML - empty values should be None, not empty strings.
    This ensures `if not entity:` guards work correctly in executor actions.

    Args:
        value: Any value from config (str, None, or other)

    Returns:
        str if value is non-empty string, None otherwise
    """
    if value is None or value == "" or str(value).strip() == "":
        return None
    return str(value)


def _parse_departure_time(value: Any) -> str | None:
    """Parse departure time from config value.

    Handles both string "HH:MM" format and integer minutes-since-midnight (0-1439).
    Defensive conversion for YAML 1.1 sexagesimal misparse (e.g., 16:00 -> 960).

    Args:
        value: Any value from config (str, int, None, or other)

    Returns:
        str in "HH:MM" format if valid, None otherwise
    """
    if value is None or value == "":
        return None

    if isinstance(value, int):
        if 0 <= value <= 1439:
            return f"{value // 60:02d}:{value % 60:02d}"
        return None

    return str(value) or None


@dataclass
class InverterConfig:
    """Inverter control entity configuration."""

    # Standardized names (Rev IP4)
    work_mode: str | None = None
    soc_target: str | None = None
    grid_charging_enable: str | None = None
    grid_charge_power: str | None = None
    minimum_reserve: str | None = None
    grid_max_export_power: str | None = None
    max_charge_current: str | None = None
    max_discharge_current: str | None = None
    grid_max_export_power_switch: str | None = None
    max_charge_power: str | None = None
    max_discharge_power: str | None = None

    # Control unit (A or W)
    control_unit: str = "A"

    # Dynamic entities for complex profiles (Rev IP2)
    custom_entities: dict[str, str | None] = field(default_factory=dict[str, str | None])


@dataclass
class WaterHeaterGlobalConfig:
    """Global water heater temperature configuration (house-level preferences)."""

    temp_normal: int = 60
    temp_off: int = 40
    temp_boost: int = 70
    temp_max: int = 85


# Backward compatibility alias
WaterHeaterConfig = WaterHeaterGlobalConfig


class ExcessPVSinkType(Enum):
    """Type of excess PV sink."""

    WATER_HEATER_BOOST = "water_heater_boost"
    CUSTOM_ENTITY = "custom_entity"
    DISABLED = "disabled"


@dataclass
class ExcessPVCustomEntityConfig:
    """Custom HA entity configuration for excess PV sink."""

    entity: str | None = None
    on_value: str = "1"
    off_value: str = "0"
    power_kw: float = 1.0


@dataclass
class ExcessPVConfig:
    """Excess PV dispatch configuration."""

    sink: ExcessPVSinkType = ExcessPVSinkType.DISABLED
    boost_reward_sek_per_kwh: float = 0.5
    soc_threshold_percent: float = 95.0
    custom_entity: ExcessPVCustomEntityConfig = field(default_factory=ExcessPVCustomEntityConfig)


@dataclass
class WaterHeaterDeviceConfig:
    """Per-device water heater control configuration."""

    id: str = ""
    name: str = ""
    target_entity: str | None = None
    power_kw: float = 3.0


DEFAULT_PENALTY_LEVELS = {
    "emergency": 10.0,
    "high": 2.0,
    "normal": 0.5,
    "opportunistic": 0.1,
}


@dataclass
class EVChargerConfig:
    """EV charger control configuration (legacy single-charger)."""

    switch_entity: str | None = None
    max_power_kw: float = 7.4
    battery_capacity_kwh: float | None = None
    replan_on_plugin: bool = True
    replan_on_unplug: bool = False


@dataclass
class EVChargerDeviceConfig:
    """Per-device EV charger configuration."""

    id: str = ""
    switch_entity: str | None = None
    max_power_kw: float = 7.4
    battery_capacity_kwh: float | None = None
    replan_on_plugin: bool = True
    replan_on_unplug: bool = False
    departure_time: str | None = None


@dataclass
class NotificationConfig:
    """Notification settings per action type."""

    service: str | None = None
    on_charge_start: bool = True
    on_charge_stop: bool = False
    on_export_start: bool = True
    on_export_stop: bool = True
    on_water_heat_start: bool = True
    on_water_heat_stop: bool = False
    on_soc_target_change: bool = False
    on_override_activated: bool = True
    on_error: bool = True


@dataclass
class ControllerConfig:
    """Controller parameters for current/power calculations."""

    battery_capacity_kwh: float = 27.0
    nominal_voltage_v: float = 48.0
    min_voltage_v: float = 46.0
    min_charge_a: float = 10.0
    max_charge_a: float = 185.0
    max_discharge_a: float = 185.0
    round_step_a: float = 5.0
    write_threshold_a: float = 5.0
    # Watt-based limits
    max_charge_w: float = 5000.0
    max_discharge_w: float = 5000.0
    min_charge_w: float = 500.0
    round_step_w: float = 100.0
    write_threshold_w: float = 100.0
    charge_efficiency: float = 0.92


@dataclass
class ExecutorConfig:
    """Main executor configuration."""

    enabled: bool = False
    shadow_mode: bool = False  # Log only, don't execute
    interval_seconds: int = 300  # 5 minutes

    automation_toggle_entity: str | None = None
    manual_override_entity: str | None = None

    inverter: InverterConfig = field(default_factory=InverterConfig)
    water_heater: WaterHeaterGlobalConfig = field(default_factory=WaterHeaterGlobalConfig)
    water_heater_devices: list[WaterHeaterDeviceConfig] = field(default_factory=lambda: [])
    ev_charger: EVChargerConfig = field(default_factory=EVChargerConfig)  # legacy compat
    ev_chargers: list[EVChargerDeviceConfig] = field(default_factory=lambda: [])
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    controller: ControllerConfig = field(default_factory=ControllerConfig)
    excess_pv: ExcessPVConfig = field(default_factory=ExcessPVConfig)

    history_retention_days: int = 30
    schedule_path: str = "data/schedule.json"
    timezone: str = "Europe/Stockholm"
    pause_reminder_minutes: int = 30  # Send notification after N minutes paused
    max_schedule_age_hours: int = 6  # Reject stale schedules older than this

    # System profile toggles (Rev O1)
    has_solar: bool = True
    has_battery: bool = True
    has_water_heater: bool = True
    inverter_profile: str = "generic"


def load_yaml(path: str) -> dict[str, Any]:
    """Load YAML file with strict typing."""
    try:
        with Path(path).open(encoding="utf-8") as f:
            yaml_loader = YAML(typ="safe")
            raw_data = yaml_loader.load(f)  # pyright: ignore[reportUnknownMemberType]
            return cast("dict[str, Any]", raw_data) if isinstance(raw_data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.error("Failed to load YAML %s: %s", path, e)
        return {}


def load_executor_config(config_path: str = "config.yaml") -> ExecutorConfig:
    """
    Load executor configuration from config.yaml.

    Falls back to defaults if executor section is missing.
    """
    try:
        with Path(config_path).open(encoding="utf-8") as f:
            yaml_loader = YAML(typ="safe")
            raw_data = yaml_loader.load(f)  # pyright: ignore[reportUnknownMemberType]
            data: dict[str, Any] = (
                cast("dict[str, Any]", raw_data) if isinstance(raw_data, dict) else {}
            )
    except FileNotFoundError:
        logger.warning("Config file not found at %s, using defaults", config_path)
        return ExecutorConfig()
    except Exception as e:
        logger.error("Failed to load config: %s", e)
        return ExecutorConfig()

    # Get timezone from root config
    timezone = str(data.get("timezone", "Europe/Stockholm"))

    # System toggles (Rev O1)
    system_data: dict[str, Any] = (
        data.get("system", {}) if isinstance(data.get("system"), dict) else {}
    )
    has_solar = bool(system_data.get("has_solar", True))
    has_battery = bool(system_data.get("has_battery", True))
    has_water_heater = bool(system_data.get("has_water_heater", True))
    inverter_profile = str(system_data.get("inverter_profile", "generic"))

    executor_data: dict[str, Any] = (
        data.get("executor", {}) if isinstance(data.get("executor"), dict) else {}
    )
    if not executor_data:
        logger.info("No executor section in config, using defaults")
        return ExecutorConfig(timezone=timezone)

    # Parse nested configs
    inverter_data: dict[str, Any] = (
        executor_data.get("inverter", {}) if isinstance(executor_data.get("inverter"), dict) else {}
    )

    # Helper for fallback loading
    def get_ent(key: str, old_key: str) -> str | None:
        return _str_or_none(inverter_data.get(key) or inverter_data.get(old_key))

    inverter = InverterConfig(
        work_mode=get_ent("work_mode", "work_mode_entity"),
        soc_target=_str_or_none(
            inverter_data.get("soc_target")
            or inverter_data.get("soc_target_entity")
            or executor_data.get("soc_target_entity")  # Fallback to legacy root location
        ),
        grid_charging_enable=get_ent("grid_charging_enable", "grid_charging_entity"),
        grid_charge_power=get_ent("grid_charge_power", "grid_charge_power_entity"),
        minimum_reserve=get_ent("minimum_reserve", "minimum_reserve_entity"),
        grid_max_export_power=get_ent("grid_max_export_power", "grid_max_export_power_entity"),
        grid_max_export_power_switch=get_ent(
            "grid_max_export_power_switch", "grid_max_export_power_switch_entity"
        ),
        max_charge_current=get_ent("max_charge_current", "max_charging_current_entity"),
        max_discharge_current=get_ent("max_discharge_current", "max_discharging_current_entity"),
        max_charge_power=get_ent("max_charge_power", "max_charging_power_entity"),
        max_discharge_power=get_ent("max_discharge_power", "max_discharging_power_entity"),
        control_unit=str(inverter_data.get("control_unit", "A")),
        # Capture all other keys as custom entities (Rev IP2)
        # REV F71: Add "custom_entities" to exclusion set to prevent stringification of nested dict
        custom_entities={
            k: _str_or_none(v)
            for k, v in inverter_data.items()
            if k
            not in {
                "work_mode",
                "work_mode_entity",
                "soc_target",
                "soc_target_entity",
                "grid_charging_enable",
                "grid_charging_entity",
                "grid_charge_power",
                "grid_charge_power_entity",
                "minimum_reserve",
                "minimum_reserve_entity",
                "grid_max_export_power",
                "grid_max_export_power_entity",
                "grid_max_export_power_switch",
                "grid_max_export_power_switch_entity",
                "max_charge_current",
                "max_charging_current_entity",
                "max_discharge_current",
                "max_discharging_current_entity",
                "max_charge_power",
                "max_charging_power_entity",
                "max_discharge_power",
                "max_discharging_power_entity",
                "control_unit",
                "custom_entities",  # REV F71: Don't stringify nested custom_entities dict
            }
        },
    )

    # REV F71: Explicitly merge nested custom_entities from YAML
    # This handles the case where users define custom_entities as a nested dict
    nested_custom: dict[str, Any] = (
        inverter_data.get("custom_entities", {})
        if isinstance(inverter_data.get("custom_entities"), dict)
        else {}
    )
    for k, v in nested_custom.items():
        if k not in inverter.custom_entities or inverter.custom_entities.get(k) is None:
            inverter.custom_entities[k] = _str_or_none(v)

    water_data: dict[str, Any] = (
        executor_data.get("water_heater", {})
        if isinstance(executor_data.get("water_heater"), dict)
        else {}
    )

    # Global water heater temperature config (house-level preferences, from executor.water_heater)
    water_heater = WaterHeaterGlobalConfig(
        temp_normal=int(water_data.get("temp_normal", WaterHeaterGlobalConfig.temp_normal)),
        temp_off=int(water_data.get("temp_off", WaterHeaterGlobalConfig.temp_off)),
        temp_boost=int(water_data.get("temp_boost", WaterHeaterGlobalConfig.temp_boost)),
        temp_max=int(water_data.get("temp_max", WaterHeaterGlobalConfig.temp_max)),
    )

    # Per-device water heater configs (from water_heaters[] array)
    water_heaters_array = data.get("water_heaters", [])
    water_heater_devices_list: list[WaterHeaterDeviceConfig] = []
    for idx, heater in enumerate(cast("list[dict[str, Any]]", water_heaters_array)):
        if not heater.get("enabled", True):
            continue
        target_ent = _str_or_none(heater.get("target_entity"))
        if not target_ent:
            continue  # Only include heaters with a target_entity
        heater_id = str(heater.get("id", f"water_heater_{idx}"))
        water_heater_devices_list.append(
            WaterHeaterDeviceConfig(
                id=heater_id,
                name=str(heater.get("name", heater_id)),
                target_entity=target_ent,
                power_kw=float(heater.get("power_kw", WaterHeaterDeviceConfig.power_kw)),
            )
        )

    # EV Charger config (REV K25 Phase 5)
    ev_data: dict[str, Any] = (
        executor_data.get("ev_charger", {})
        if isinstance(executor_data.get("ev_charger"), dict)
        else {}
    )
    ev_charger = EVChargerConfig(
        switch_entity=_str_or_none(ev_data.get("switch_entity")),
        max_power_kw=float(ev_data.get("max_power_kw", EVChargerConfig.max_power_kw)),
        battery_capacity_kwh=ev_data.get("battery_capacity_kwh"),
        replan_on_plugin=bool(ev_data.get("replan_on_plugin", EVChargerConfig.replan_on_plugin)),
        replan_on_unplug=bool(ev_data.get("replan_on_unplug", EVChargerConfig.replan_on_unplug)),
    )

    # Per-device EV charger config (multi-device support)
    ev_chargers_array = data.get("ev_chargers", [])
    ev_chargers_list: list[EVChargerDeviceConfig] = []
    for idx, charger in enumerate(cast("list[dict[str, Any]]", ev_chargers_array)):
        if not charger.get("enabled", True):
            continue
        charger_id = str(charger.get("id", f"ev_charger_{idx}"))
        ev_chargers_list.append(
            EVChargerDeviceConfig(
                id=charger_id,
                switch_entity=_str_or_none(charger.get("switch_entity")),
                max_power_kw=float(
                    charger.get("max_power_kw") or EVChargerDeviceConfig.max_power_kw
                ),
                battery_capacity_kwh=charger.get("battery_capacity_kwh"),
                replan_on_plugin=bool(
                    charger.get("replan_on_plugin", EVChargerDeviceConfig.replan_on_plugin)
                ),
                replan_on_unplug=bool(
                    charger.get("replan_on_unplug", EVChargerDeviceConfig.replan_on_unplug)
                ),
                departure_time=_parse_departure_time(charger.get("departure_time")),
            )
        )

    notif_data: dict[str, Any] = (
        executor_data.get("notifications", {})
        if isinstance(executor_data.get("notifications"), dict)
        else {}
    )
    notifications = NotificationConfig(
        service=_str_or_none(notif_data.get("service", NotificationConfig.service)),
        on_charge_start=bool(notif_data.get("on_charge_start", NotificationConfig.on_charge_start)),
        on_charge_stop=bool(notif_data.get("on_charge_stop", NotificationConfig.on_charge_stop)),
        on_export_start=bool(notif_data.get("on_export_start", NotificationConfig.on_export_start)),
        on_export_stop=bool(notif_data.get("on_export_stop", NotificationConfig.on_export_stop)),
        on_water_heat_start=bool(
            notif_data.get("on_water_heat_start", NotificationConfig.on_water_heat_start)
        ),
        on_water_heat_stop=bool(
            notif_data.get("on_water_heat_stop", NotificationConfig.on_water_heat_stop)
        ),
        on_soc_target_change=bool(
            notif_data.get("on_soc_target_change", NotificationConfig.on_soc_target_change)
        ),
        on_override_activated=bool(
            notif_data.get("on_override_activated", NotificationConfig.on_override_activated)
        ),
        on_error=bool(notif_data.get("on_error", NotificationConfig.on_error)),
    )

    # Root battery config (New SSOT for REV F17)
    battery_data: dict[str, Any] = (
        data.get("battery", {}) if isinstance(data.get("battery"), dict) else {}
    )

    ctrl_data: dict[str, Any] = (
        executor_data.get("controller", {})
        if isinstance(executor_data.get("controller"), dict)
        else {}
    )

    # Function to get with fallback (Rev F17 Migration)
    def get_fb(
        key: str,
        legacy_key: str,
        default: Any,
        source: dict[str, Any] = battery_data,
        legacy_source: dict[str, Any] = ctrl_data,
    ) -> Any:
        # 1. Try new source
        val: Any = source.get(key)
        if val is not None:
            return val
        # 2. Try legacy source
        val = legacy_source.get(legacy_key)
        if val is not None:
            # logger.warning(f"Using legacy config key '{legacy_key}'. Please move to battery section.") # Logged by migration module
            return val
        return default

    controller = ControllerConfig(
        battery_capacity_kwh=float(
            str(
                get_fb(
                    "capacity_kwh", "battery_capacity_kwh", ControllerConfig.battery_capacity_kwh
                )
            )
        ),
        nominal_voltage_v=float(
            str(get_fb("nominal_voltage_v", "system_voltage_v", ControllerConfig.nominal_voltage_v))
        ),
        min_voltage_v=float(
            str(get_fb("min_voltage_v", "worst_case_voltage_v", ControllerConfig.min_voltage_v))
        ),
        min_charge_a=float(str(ctrl_data.get("min_charge_a", ControllerConfig.min_charge_a))),
        max_charge_a=float(
            str(get_fb("max_charge_a", "max_charge_a", ControllerConfig.max_charge_a))
        ),
        max_discharge_a=float(
            str(get_fb("max_discharge_a", "max_discharge_a", ControllerConfig.max_discharge_a))
        ),
        round_step_a=float(str(ctrl_data.get("round_step_a", ControllerConfig.round_step_a))),
        write_threshold_a=float(
            str(ctrl_data.get("write_threshold_a", ControllerConfig.write_threshold_a))
        ),
        max_charge_w=float(
            str(get_fb("max_charge_w", "max_charge_w", ControllerConfig.max_charge_w))
        ),
        max_discharge_w=float(
            str(get_fb("max_discharge_w", "max_discharge_w", ControllerConfig.max_discharge_w))
        ),
        min_charge_w=float(str(ctrl_data.get("min_charge_w", ControllerConfig.min_charge_w))),
        round_step_w=float(str(ctrl_data.get("round_step_w", ControllerConfig.round_step_w))),
        write_threshold_w=float(
            str(ctrl_data.get("write_threshold_w", ControllerConfig.write_threshold_w))
        ),
        charge_efficiency=float(
            str(ctrl_data.get("charge_efficiency", ControllerConfig.charge_efficiency))
        ),
    )

    excess_pv_data: dict[str, Any] = (
        executor_data.get("excess_pv", {})
        if isinstance(executor_data.get("excess_pv"), dict)
        else {}
    )
    sink_raw = str(excess_pv_data.get("sink", "disabled")).lower()
    try:
        sink_type = ExcessPVSinkType(sink_raw)
    except ValueError:
        sink_type = ExcessPVSinkType.DISABLED

    custom_entity_data: dict[str, Any] = (
        excess_pv_data.get("custom_entity", {})
        if isinstance(excess_pv_data.get("custom_entity"), dict)
        else {}
    )
    custom_entity = ExcessPVCustomEntityConfig(
        entity=_str_or_none(custom_entity_data.get("entity")),
        on_value=str(custom_entity_data.get("on_value", "1")),
        off_value=str(custom_entity_data.get("off_value", "0")),
        power_kw=float(custom_entity_data.get("power_kw", 1.0)),
    )
    excess_pv = ExcessPVConfig(
        sink=sink_type,
        boost_reward_sek_per_kwh=float(excess_pv_data.get("boost_reward_sek_per_kwh", 0.5)),
        soc_threshold_percent=float(excess_pv_data.get("soc_threshold_percent", 95.0)),
        custom_entity=custom_entity,
    )

    return ExecutorConfig(
        enabled=bool(executor_data.get("enabled", False)),
        shadow_mode=bool(executor_data.get("shadow_mode", False)),
        interval_seconds=int(executor_data.get("interval_seconds", 300)),
        automation_toggle_entity=_str_or_none(executor_data.get("automation_toggle_entity")),
        manual_override_entity=_str_or_none(executor_data.get("manual_override_entity")),
        inverter=inverter,
        water_heater=water_heater,
        water_heater_devices=water_heater_devices_list,
        ev_charger=ev_charger,
        ev_chargers=ev_chargers_list,
        notifications=notifications,
        controller=controller,
        excess_pv=excess_pv,
        history_retention_days=int(executor_data.get("history_retention_days", 30)),
        schedule_path=str(executor_data.get("schedule_path", "data/schedule.json")),
        timezone=timezone,
        pause_reminder_minutes=int(executor_data.get("pause_reminder_minutes", 30)),
        max_schedule_age_hours=int(executor_data.get("max_schedule_age_hours", 6)),
        has_solar=has_solar,
        has_battery=has_battery,
        has_water_heater=has_water_heater,
        inverter_profile=inverter_profile,
    )
