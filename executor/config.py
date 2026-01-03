"""
Executor Configuration

Loads and validates the executor configuration from config.yaml.
"""

import logging
from dataclasses import dataclass, field

from typing import Any, cast
import yaml

logger = logging.getLogger(__name__)


@dataclass
class InverterConfig:
    """Inverter control entity configuration."""

    work_mode_entity: str = "select.inverter_work_mode"
    work_mode_export: str = "Export First"
    work_mode_zero_export: str = "Zero Export To CT"
    grid_charging_entity: str = "switch.inverter_battery_grid_charging"
    max_charging_current_entity: str = "number.inverter_battery_max_charging_current"
    max_discharging_current_entity: str = "number.inverter_battery_max_discharging_current"


@dataclass
class WaterHeaterConfig:
    """Water heater control configuration."""

    target_entity: str = "input_number.vvbtemp"
    temp_normal: int = 60
    temp_off: int = 40
    temp_boost: int = 70
    temp_max: int = 85


@dataclass
class NotificationConfig:
    """Notification settings per action type."""

    service: str = "notify.mobile_app_phone"
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
    system_voltage_v: float = 48.0
    worst_case_voltage_v: float = 46.0
    min_charge_a: float = 10.0
    max_charge_a: float = 190.0
    round_step_a: float = 5.0
    write_threshold_a: float = 5.0
    inverter_ac_limit_kw: float = 8.8
    charge_efficiency: float = 0.92


@dataclass
class ExecutorConfig:
    """Main executor configuration."""

    enabled: bool = False
    shadow_mode: bool = False  # Log only, don't execute
    interval_seconds: int = 300  # 5 minutes

    automation_toggle_entity: str = "input_boolean.helios_ai_mode"
    manual_override_entity: str = "input_boolean.darkstar_manual_override"
    soc_target_entity: str = "input_number.master_soc_target"

    inverter: InverterConfig = field(default_factory=InverterConfig)
    water_heater: WaterHeaterConfig = field(default_factory=WaterHeaterConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    controller: ControllerConfig = field(default_factory=ControllerConfig)

    history_retention_days: int = 30
    schedule_path: str = "schedule.json"
    timezone: str = "Europe/Stockholm"
    pause_reminder_minutes: int = 30  # Send notification after N minutes paused

    # System profile toggles (Rev O1)
    has_solar: bool = True
    has_battery: bool = True
    has_water_heater: bool = True


def load_executor_config(config_path: str = "config.yaml") -> ExecutorConfig:
    """
    Load executor configuration from config.yaml.

    Falls back to defaults if executor section is missing.
    """
    try:
        with open(config_path, encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)
            data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    except FileNotFoundError:
        logger.warning("Config file not found at %s, using defaults", config_path)
        return ExecutorConfig()
    except Exception as e:
        logger.error("Failed to load config: %s", e)
        return ExecutorConfig()

    # Get timezone from root config
    timezone = str(data.get("timezone", "Europe/Stockholm"))

    # System toggles (Rev O1)
    system_data: dict[str, Any] = data.get("system", {}) if isinstance(data.get("system"), dict) else {}
    has_solar = bool(system_data.get("has_solar", True))
    has_battery = bool(system_data.get("has_battery", True))
    has_water_heater = bool(system_data.get("has_water_heater", True))

    executor_data: dict[str, Any] = data.get("executor", {}) if isinstance(data.get("executor"), dict) else {}
    if not executor_data:
        logger.info("No executor section in config, using defaults")
        return ExecutorConfig(timezone=timezone)

    # Parse nested configs
    inverter_data: dict[str, Any] = executor_data.get("inverter", {}) if isinstance(executor_data.get("inverter"), dict) else {}
    inverter = InverterConfig(
        work_mode_entity=str(inverter_data.get("work_mode_entity", InverterConfig.work_mode_entity)),
        work_mode_export=str(inverter_data.get("work_mode_export", InverterConfig.work_mode_export)),
        work_mode_zero_export=str(inverter_data.get(
            "work_mode_zero_export", InverterConfig.work_mode_zero_export
        )),
        grid_charging_entity=str(inverter_data.get(
            "grid_charging_entity", InverterConfig.grid_charging_entity
        )),
        max_charging_current_entity=str(inverter_data.get(
            "max_charging_current_entity", InverterConfig.max_charging_current_entity
        )),
        max_discharging_current_entity=str(inverter_data.get(
            "max_discharging_current_entity", InverterConfig.max_discharging_current_entity
        )),
    )

    water_data: dict[str, Any] = executor_data.get("water_heater", {}) if isinstance(executor_data.get("water_heater"), dict) else {}
    water_heater = WaterHeaterConfig(
        target_entity=str(water_data.get("target_entity", WaterHeaterConfig.target_entity)),
        temp_normal=int(water_data.get("temp_normal", WaterHeaterConfig.temp_normal)),
        temp_off=int(water_data.get("temp_off", WaterHeaterConfig.temp_off)),
        temp_boost=int(water_data.get("temp_boost", WaterHeaterConfig.temp_boost)),
        temp_max=int(water_data.get("temp_max", WaterHeaterConfig.temp_max)),
    )

    notif_data: dict[str, Any] = executor_data.get("notifications", {}) if isinstance(executor_data.get("notifications"), dict) else {}
    notifications = NotificationConfig(
        service=str(notif_data.get("service", NotificationConfig.service)),
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

    ctrl_data: dict[str, Any] = executor_data.get("controller", {}) if isinstance(executor_data.get("controller"), dict) else {}
    controller = ControllerConfig(
        battery_capacity_kwh=float(
            str(ctrl_data.get("battery_capacity_kwh", ControllerConfig.battery_capacity_kwh))
        ),
        system_voltage_v=float(
            str(ctrl_data.get("system_voltage_v", ControllerConfig.system_voltage_v))
        ),
        worst_case_voltage_v=float(
            str(ctrl_data.get("worst_case_voltage_v", ControllerConfig.worst_case_voltage_v))
        ),
        min_charge_a=float(str(ctrl_data.get("min_charge_a", ControllerConfig.min_charge_a))),
        max_charge_a=float(str(ctrl_data.get("max_charge_a", ControllerConfig.max_charge_a))),
        round_step_a=float(str(ctrl_data.get("round_step_a", ControllerConfig.round_step_a))),
        write_threshold_a=float(
            str(ctrl_data.get("write_threshold_a", ControllerConfig.write_threshold_a))
        ),
        inverter_ac_limit_kw=float(
            str(ctrl_data.get("inverter_ac_limit_kw", ControllerConfig.inverter_ac_limit_kw))
        ),
        charge_efficiency=float(
            str(ctrl_data.get("charge_efficiency", ControllerConfig.charge_efficiency))
        ),
    )

    return ExecutorConfig(
        enabled=bool(executor_data.get("enabled", False)),
        shadow_mode=bool(executor_data.get("shadow_mode", False)),
        interval_seconds=int(executor_data.get("interval_seconds", 300)),
        automation_toggle_entity=str(executor_data.get(
            "automation_toggle_entity", ExecutorConfig.automation_toggle_entity
        )),
        manual_override_entity=str(executor_data.get(
            "manual_override_entity", ExecutorConfig.manual_override_entity
        )),
        soc_target_entity=str(executor_data.get("soc_target_entity", ExecutorConfig.soc_target_entity)),
        inverter=inverter,
        water_heater=water_heater,
        notifications=notifications,
        controller=controller,
        history_retention_days=int(executor_data.get("history_retention_days", 30)),
        schedule_path=str(executor_data.get("schedule_path", "schedule.json")),
        timezone=timezone,
        pause_reminder_minutes=int(executor_data.get("pause_reminder_minutes", 30)),
        has_solar=has_solar,
        has_battery=has_battery,
        has_water_heater=has_water_heater,
    )
