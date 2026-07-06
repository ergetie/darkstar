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
class EVChargerDeviceConfig:
    """Per-device EV charger configuration."""

    id: str = ""
    name: str = ""
    switch_entity: str | None = None
    max_power_kw: float = 7.4
    battery_capacity_kwh: float | None = None
    replan_on_plugin: bool = True
    replan_on_unplug: bool = False
    departure_time: str | None = None

    # Variable-current control (universal-load-balancing)
    type: str = "binary"  # "binary" (switch) or "current" (ampere setpoint)
    current_entity: str | None = None  # HA number entity for the ampere setpoint
    min_current_a: int = 6  # Floor below which charging pauses instead
    max_current_a: int | None = None
    phases: list[int] = field(default_factory=lambda: [1, 2, 3])

    # Per-phase draw measurement, used to derive active_phases (optional)
    phase_sensor_l1: str | None = None
    phase_sensor_l2: str | None = None
    phase_sensor_l3: str | None = None


class BalancedLoadType(Enum):
    """Type of device a load-balancing entry refers to."""

    EV_CHARGER = "ev_charger"
    WATER_HEATER = "water_heater"
    CUSTOM_ENTITY = "custom_entity"


@dataclass
class BalancedLoadConfig:
    """A single shed-able on/off load managed by the real-time load balancer.

    EV chargers configured with type="current" get dedicated ampere throttling
    (see EVChargerDeviceConfig) and do not need an entry here; this is for
    on/off shedding (water heaters, custom entities, and binary-type chargers).
    Give-way ordering lives in LoadBalancingConfig.give_way_order, not here.
    """

    device_type: BalancedLoadType = BalancedLoadType.WATER_HEATER
    device_id: str = ""
    phases: list[int] = field(default_factory=lambda: [])
    # Custom entity actuation (only used when device_type == CUSTOM_ENTITY)
    entity: str | None = None
    on_value: str = "1"
    off_value: str = "0"


@dataclass
class GiveWayOrderEntry:
    """One entry in the unified give-way order (top gives way first).

    kind="charger" references a type="current" ev_chargers[].id (throttle to
    floor, then pause); kind="shed" references a loads[].device_id (switch off).
    """

    kind: str = "shed"  # "charger" | "shed"
    id: str = ""


@dataclass
class LoadBalancingConfig:
    """Real-time per-phase load balancing (fuse protection) configuration."""

    enabled: bool = False
    # Sourced from system.grid.main_fuse_a in YAML; folded in here for convenience
    # since it is always consumed alongside the rest of this config as a unit.
    main_fuse_a: int | None = None
    resume_delay_s: int = 120
    resume_margin_percent: float = 90.0
    increase_step_a: int = 1
    sensor_stale_after_s: int = 30
    # Fallback voltage (V) for converting a power-mode phase to current when
    # that phase has no configured grid_voltage_l* entity. Unrelated to
    # ControllerConfig.nominal_voltage_v (DC battery voltage).
    nominal_voltage_v: float = 220.0
    loads: list[BalancedLoadConfig] = field(default_factory=lambda: [])
    # Unified give-way order across chargers and shed loads; the top entry
    # gives way first. Self-healed on load (see heal_give_way_order).
    give_way_order: list[GiveWayOrderEntry] = field(default_factory=lambda: [])
    # Notify (HA notify / Discord fallback) on shed, pause, and stale-fallback
    # transitions. Routine throttle/ramp adjustments never notify.
    notify_interventions: bool = False
    # Trigger one replan (via the plug/unplug replan path) after a charger has
    # been held below its planner target (or paused) this long, continuously.
    replan_after_throttled_s: int = 600


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
    ev_chargers: list[EVChargerDeviceConfig] = field(default_factory=lambda: [])
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    controller: ControllerConfig = field(default_factory=ControllerConfig)
    excess_pv: ExcessPVConfig = field(default_factory=ExcessPVConfig)
    load_balancing: LoadBalancingConfig = field(default_factory=LoadBalancingConfig)

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


def _parse_load_balancing_config(
    data: dict[str, Any], system_data: dict[str, Any]
) -> LoadBalancingConfig:
    """Parse system.grid.main_fuse_a and the top-level load_balancing: section."""
    grid_data: dict[str, Any] = (
        system_data.get("grid", {}) if isinstance(system_data.get("grid"), dict) else {}
    )
    main_fuse_a_raw = grid_data.get("main_fuse_a")
    main_fuse_a: int | None
    try:
        main_fuse_a = int(main_fuse_a_raw) if main_fuse_a_raw is not None else None
    except (TypeError, ValueError):
        logger.warning("Invalid system.grid.main_fuse_a value: %r", main_fuse_a_raw)
        main_fuse_a = None

    lb_data: dict[str, Any] = (
        data.get("load_balancing", {}) if isinstance(data.get("load_balancing"), dict) else {}
    )

    loads_raw = lb_data.get("loads", [])
    loads: list[BalancedLoadConfig] = []
    if isinstance(loads_raw, list):
        for item in cast("list[Any]", loads_raw):
            if not isinstance(item, dict):
                continue
            load_item = cast("dict[str, Any]", item)
            type_raw = str(load_item.get("device_type", "water_heater")).lower()
            try:
                device_type = BalancedLoadType(type_raw)
            except ValueError:
                logger.warning(
                    "load_balancing.loads: unknown device_type %r, skipping entry", type_raw
                )
                continue
            phases_raw = load_item.get("phases", [])
            phases = (
                [int(p) for p in cast("list[Any]", phases_raw)]
                if isinstance(phases_raw, list)
                else []
            )
            loads.append(
                BalancedLoadConfig(
                    device_type=device_type,
                    device_id=str(load_item.get("device_id", "")),
                    phases=phases,
                    entity=_str_or_none(load_item.get("entity")),
                    on_value=str(load_item.get("on_value", "1")),
                    off_value=str(load_item.get("off_value", "0")),
                )
            )

    give_way_raw = lb_data.get("give_way_order", [])
    give_way_order: list[GiveWayOrderEntry] = []
    if isinstance(give_way_raw, list):
        for item in cast("list[Any]", give_way_raw):
            if not isinstance(item, dict):
                continue
            entry_item = cast("dict[str, Any]", item)
            kind = str(entry_item.get("kind", "")).lower()
            entry_id = str(entry_item.get("id", ""))
            if kind not in ("charger", "shed") or not entry_id:
                logger.warning(
                    "load_balancing.give_way_order: invalid entry %r, skipping", entry_item
                )
                continue
            give_way_order.append(GiveWayOrderEntry(kind=kind, id=entry_id))

    return LoadBalancingConfig(
        enabled=bool(lb_data.get("enabled", False)),
        main_fuse_a=main_fuse_a,
        resume_delay_s=int(lb_data.get("resume_delay_s", LoadBalancingConfig.resume_delay_s)),
        resume_margin_percent=float(
            lb_data.get("resume_margin_percent", LoadBalancingConfig.resume_margin_percent)
        ),
        increase_step_a=int(lb_data.get("increase_step_a", LoadBalancingConfig.increase_step_a)),
        sensor_stale_after_s=int(
            lb_data.get("sensor_stale_after_s", LoadBalancingConfig.sensor_stale_after_s)
        ),
        nominal_voltage_v=float(
            lb_data.get("nominal_voltage_v", LoadBalancingConfig.nominal_voltage_v)
        ),
        loads=loads,
        give_way_order=give_way_order,
        notify_interventions=bool(lb_data.get("notify_interventions", False)),
        replan_after_throttled_s=int(
            lb_data.get("replan_after_throttled_s", LoadBalancingConfig.replan_after_throttled_s)
        ),
    )


def heal_give_way_order(lb: LoadBalancingConfig, current_type_charger_ids: list[str]) -> None:
    """Self-heal load_balancing.give_way_order on config load (in place).

    - Drops entries referencing devices that no longer exist, or chargers no
      longer type="current" (logged warning).
    - Appends current-type chargers missing from the list after the last
      charger entry (at the top when there is none).
    - Appends loads[] entries missing from the list at the end.
    """
    shed_ids = [ld.device_id for ld in lb.loads if ld.device_id]

    healed: list[GiveWayOrderEntry] = []
    for entry in lb.give_way_order:
        if (entry.kind == "charger" and entry.id in current_type_charger_ids) or (
            entry.kind == "shed" and entry.id in shed_ids
        ):
            healed.append(entry)
        else:
            logger.warning(
                "load_balancing.give_way_order: dropping %s entry '%s' — no matching "
                "%s (device removed or charger no longer type: current)",
                entry.kind,
                entry.id,
                "type: current EV charger" if entry.kind == "charger" else "loads[] entry",
            )

    listed_chargers = {e.id for e in healed if e.kind == "charger"}
    missing_chargers = [c for c in current_type_charger_ids if c not in listed_chargers]
    if missing_chargers:
        last_charger_idx = max((i for i, e in enumerate(healed) if e.kind == "charger"), default=-1)
        for offset, charger_id in enumerate(missing_chargers):
            healed.insert(
                last_charger_idx + 1 + offset, GiveWayOrderEntry(kind="charger", id=charger_id)
            )
            logger.info("load_balancing.give_way_order: appended missing charger '%s'", charger_id)

    listed_sheds = {e.id for e in healed if e.kind == "shed"}
    for shed_id in shed_ids:
        if shed_id not in listed_sheds:
            healed.append(GiveWayOrderEntry(kind="shed", id=shed_id))
            logger.info("load_balancing.give_way_order: appended missing shed load '%s'", shed_id)

    lb.give_way_order = healed


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

    # Load balancing config (top-level key, independent of the executor: section)
    load_balancing = _parse_load_balancing_config(data, system_data)

    # Self-heal give_way_order against the enabled type="current" chargers,
    # before the executor-section branch so both return paths are covered.
    ev_chargers_raw = data.get("ev_chargers", [])
    current_type_charger_ids: list[str] = []
    if isinstance(ev_chargers_raw, list):
        for idx, item in enumerate(cast("list[Any]", ev_chargers_raw)):
            if not isinstance(item, dict):
                continue
            charger_item = cast("dict[str, Any]", item)
            if not charger_item.get("enabled", True):
                continue
            if str(charger_item.get("type", "binary")).lower() != "current":
                continue
            current_type_charger_ids.append(str(charger_item.get("id", f"ev_charger_{idx}")))
    heal_give_way_order(load_balancing, current_type_charger_ids)

    executor_data: dict[str, Any] = (
        data.get("executor", {}) if isinstance(data.get("executor"), dict) else {}
    )
    if not executor_data:
        logger.info("No executor section in config, using defaults")
        return ExecutorConfig(timezone=timezone, load_balancing=load_balancing)

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

    # Per-device EV charger config (multi-device support)
    ev_chargers_array = data.get("ev_chargers", [])
    ev_chargers_list: list[EVChargerDeviceConfig] = []
    for idx, charger in enumerate(cast("list[dict[str, Any]]", ev_chargers_array)):
        if not charger.get("enabled", True):
            continue
        charger_id = str(charger.get("id", f"ev_charger_{idx}"))
        charger_phases_raw = charger.get("phases")
        charger_phases = (
            [int(p) for p in cast("list[Any]", charger_phases_raw)]
            if isinstance(charger_phases_raw, list)
            else [1, 2, 3]
        )
        ev_chargers_list.append(
            EVChargerDeviceConfig(
                id=charger_id,
                name=str(charger.get("name") or charger_id),
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
                type=str(charger.get("type", EVChargerDeviceConfig.type)).lower(),
                current_entity=_str_or_none(charger.get("current_entity")),
                min_current_a=int(
                    charger.get("min_current_a", EVChargerDeviceConfig.min_current_a)
                ),
                max_current_a=(
                    int(charger["max_current_a"])
                    if charger.get("max_current_a") is not None
                    else None
                ),
                phases=charger_phases,
                phase_sensor_l1=_str_or_none(charger.get("phase_sensor_l1")),
                phase_sensor_l2=_str_or_none(charger.get("phase_sensor_l2")),
                phase_sensor_l3=_str_or_none(charger.get("phase_sensor_l3")),
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
            str(
                get_fb("charge_efficiency", "charge_efficiency", ControllerConfig.charge_efficiency)
            )
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
        ev_chargers=ev_chargers_list,
        notifications=notifications,
        controller=controller,
        excess_pv=excess_pv,
        load_balancing=load_balancing,
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


_MOCK_ENTITY_PATTERNS = ("mock", "test")


def _is_mock_entity(entity: str | None) -> bool:
    if not entity:
        return False
    lowered = entity.lower()
    return any(pattern in lowered for pattern in _MOCK_ENTITY_PATTERNS)


def check_mock_entities(config: ExecutorConfig) -> list[str]:
    """Warn (non-blocking) when an enabled device targets a mock/test entity id.

    A production instance should never silently plan capacity around a phantom
    device; the operator's local mock setup is legitimate but should be visible.
    """
    warnings: list[str] = []

    for heater in config.water_heater_devices:
        if _is_mock_entity(heater.target_entity):
            warnings.append(
                f"Water heater '{heater.name}' is ENABLED but targets a mock/test "
                f"entity: {heater.target_entity}"
            )

    for charger in config.ev_chargers:
        if _is_mock_entity(charger.switch_entity):
            warnings.append(
                f"EV charger '{charger.id}' is ENABLED but targets a mock/test "
                f"entity: {charger.switch_entity}"
            )

    if config.has_battery:
        inverter_entities = {
            "work_mode": config.inverter.work_mode,
            "soc_target": config.inverter.soc_target,
            "grid_charging_enable": config.inverter.grid_charging_enable,
            "grid_charge_power": config.inverter.grid_charge_power,
            "minimum_reserve": config.inverter.minimum_reserve,
            "grid_max_export_power": config.inverter.grid_max_export_power,
            "max_charge_current": config.inverter.max_charge_current,
            "max_discharge_current": config.inverter.max_discharge_current,
            "max_charge_power": config.inverter.max_charge_power,
            "max_discharge_power": config.inverter.max_discharge_power,
        }
        mock_field = next(
            (
                field_name
                for field_name, entity in inverter_entities.items()
                if _is_mock_entity(entity)
            ),
            None,
        )
        if mock_field:
            warnings.append(
                f"Inverter is ENABLED but targets a mock/test entity "
                f"({mock_field}): {inverter_entities[mock_field]}"
            )

    for warning in warnings:
        logger.warning(warning)

    return warnings
