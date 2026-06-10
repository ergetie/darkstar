"""Config migration module.

Startup validation and migration: deprecated-key sweep, template merge, atomic write with backup.
"""

import contextlib
import errno
import io
import logging
import os
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, cast

try:
    from ruamel.yaml import YAML
except ImportError:
    # Fallback if ruamel.yaml is not available (should be in requirements.txt)
    YAML = None  # type: ignore[misc,assignment]

logger = logging.getLogger("darkstar.config_migration")

BACKUP_DIR_ENV = "BACKUP_DIR"
HOST_BACKUP_DIR = Path("/host_backups")
CURRENT_CONFIG_VERSION = 2


def _get_persistent_backup_dir(config_path: Path) -> Path:
    """Return the backup directory to use for the given config path."""
    # Detect HA add-on deployment: config lives at /config/darkstar/
    if str(config_path).startswith("/config/darkstar/"):
        ha_backup_dir = Path("/share/darkstar/backups")
        logger.debug("Detected HA add-on deployment, using: %s", ha_backup_dir)
        return ha_backup_dir

    if HOST_BACKUP_DIR.exists() and HOST_BACKUP_DIR.is_dir():
        logger.debug("Using host-mounted backup directory: %s", HOST_BACKUP_DIR)
        return HOST_BACKUP_DIR

    backup_dir_env = os.environ.get(BACKUP_DIR_ENV)
    if backup_dir_env:
        env_path = Path(backup_dir_env)
        if env_path.is_absolute():
            logger.debug("Using BACKUP_DIR env var: %s", env_path)
            return env_path
        else:
            relative_path = config_path.parent / env_path
            logger.debug("Using relative BACKUP_DIR env var: %s", relative_path)
            return relative_path

    local_backup_dir = config_path.parent / "backups"
    if Path("/.dockerenv").exists():
        logger.warning(
            "Container detected but no /host_backups mount found. "
            "Backups will be ephemeral at %s. Consider mounting a volume.",
            local_backup_dir,
        )
    return local_backup_dir


# Type alias for migration functions
# Returns: (modified_config, changed_bool)
MigrationStep = Callable[[dict[str, Any]], tuple[dict[str, Any], bool]]


# =============================================================================
# Centralized Deprecated Keys Registry
# =============================================================================
# These keys MUST be removed during migration to prevent corruption

# Root-level deprecated keys
DEPRECATED_KEYS = {
    "deferrable_loads",  # Replaced by water_heaters[] and ev_chargers[]
    "ev_charger",  # Replaced by ev_chargers[] array (plural)
    "ev_departure_time",  # Moved into ev_chargers[].departure_time
    "solar_array",  # Replaced by solar_arrays[] array (plural)
    "version",  # Replaced by config_version
    "schedule_future_only",  # Removed
}

# Nested deprecated keys (path.to.key format)
DEPRECATED_NESTED_KEYS = {
    "executor.ev_charger": [
        "switch_entity",  # Moved into ev_chargers[].switch_entity
        "replan_on_plugin",  # Moved into ev_chargers[].replan_on_plugin
        "replan_on_unplug",  # Moved into ev_chargers[].replan_on_unplug
    ],
    "executor.inverter": [
        # Old _entity suffix keys replaced by standardized names
        "work_mode_entity",
        "soc_target_entity",
        "grid_charging_entity",
        "max_charging_current_entity",
        "max_discharging_current_entity",
        "max_charging_power_entity",
        "max_discharging_power_entity",
        "grid_max_export_power_entity",
        "grid_charge_power_entity",
        "minimum_reserve_entity",
    ],
    "system": [
        # Replaced by solar_arrays[] array (plural)
        "solar_array",
    ],
    "system.inverter": [
        # Migrated to max_ac_power_kw
        "max_power_kw",
    ],
    "water_heating": [
        # These keys should be in water_heaters[] array items, not flat under water_heating
        "power_kw",
        "min_kwh_per_day",
        "target_temp_c",
        "heating_element_entity",
        "temperature_sensor_entity",
        "daily_consumption_entity",
        "max_price_per_kwh",
    ],
    "executor.override": [
        "low_soc_export_floor",  # Moved to export.export_floor_soc_percent
        "excess_pv_threshold_kw",  # Removed: excess PV now handled by planner
    ],
}


def remove_deprecated_keys(config: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Remove all deprecated keys from config.

    Centralized cleanup to prevent corrupted configs with legacy keys.

    Args:
        config: Configuration dict to clean

    Returns:
        Tuple of (cleaned_config, changed_flag)
    """
    changed = False

    # Root-level deprecated keys
    for key in DEPRECATED_KEYS:
        if key in config:
            del config[key]
            logger.info(f"✂️  Removed deprecated key: '{key}'")
            changed = True

    # Nested deprecated keys
    for path, keys in DEPRECATED_NESTED_KEYS.items():
        parts = path.split(".")
        obj = config

        # Navigate to nested object
        for part in parts:
            if isinstance(obj, dict) and part in obj:
                obj = obj[part]
            else:
                break
        else:
            # Object exists, clean deprecated keys
            if isinstance(obj, dict):
                for key in keys:
                    if key in obj:
                        del obj[key]
                        logger.info(f"✂️  Removed deprecated key: '{path}.{key}'")
                        changed = True

    return config, changed


def _migrate_water_heater_fields(config: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Migrate legacy water heater config fields into water_heaters[] array.

    Copies:
      - input_sensors.water_power -> water_heaters[0].sensor (if sensor is empty)
      - input_sensors.water_heater_consumption -> water_heaters[0].energy_sensor (if empty)
      - executor.water_heater.target_entity -> water_heaters[0].target_entity (if missing/empty)

    Then removes the old keys.

    Returns:
        Tuple of (modified_config, changed_flag)
    """
    changed = False

    # Get water_heaters array, create if doesn't exist
    water_heaters = config.get("water_heaters", [])
    if not water_heaters or not isinstance(water_heaters, list):
        # No water heaters configured, nothing to migrate
        return config, changed

    # Work on first heater
    first_heater = cast("dict[str, Any]", water_heaters[0])

    # Get input_sensors and executor.water_heater sections
    input_sensors = cast("dict[str, Any]", config.get("input_sensors", {}))
    executor = cast("dict[str, Any]", config.get("executor", {}))
    water_heater_config = cast("dict[str, Any]", executor.get("water_heater", {}))

    # 1. Migrate water_power -> sensor
    old_water_power = input_sensors.get("water_power", "")
    current_sensor = first_heater.get("sensor", "")
    if old_water_power and not current_sensor:
        first_heater["sensor"] = old_water_power
        logger.info(
            f"🔄 Migrated input_sensors.water_power -> water_heaters[0].sensor: {old_water_power}"
        )
        changed = True

    # 2. Migrate executor.water_heater.target_entity -> target_entity
    old_target = water_heater_config.get("target_entity", "")
    current_target = first_heater.get("target_entity", "")
    if old_target and not current_target:
        first_heater["target_entity"] = old_target
        logger.info(
            f"🔄 Migrated executor.water_heater.target_entity -> water_heaters[0].target_entity: {old_target}"
        )
        changed = True

    # 4. Remove old keys after migration
    if "water_power" in input_sensors:
        del input_sensors["water_power"]
        logger.info("✂️  Removed deprecated key: 'input_sensors.water_power'")
        changed = True
    if "water_heater_consumption" in input_sensors:
        del input_sensors["water_heater_consumption"]
        logger.info("✂️  Removed deprecated key: 'input_sensors.water_heater_consumption'")
        changed = True

    if "target_entity" in water_heater_config:
        del water_heater_config["target_entity"]
        logger.info("✂️  Removed deprecated key: 'executor.water_heater.target_entity'")
        changed = True

    return config, changed


def _migrate_ev_charger_fields(config: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Migrate global EV charger settings into the first enabled ev_chargers[] entry.

    Copies:
      - ev_departure_time (root) -> ev_chargers[0].departure_time (if absent/empty)
      - executor.ev_charger.switch_entity -> ev_chargers[0].switch_entity (if absent/empty)
      - executor.ev_charger.replan_on_plugin -> ev_chargers[0].replan_on_plugin (if absent)
      - executor.ev_charger.replan_on_unplug -> ev_chargers[0].replan_on_unplug (if absent)

    Returns:
        Tuple of (modified_config, changed_flag)
    """
    changed = False

    ev_chargers = config.get("ev_chargers", [])
    if not ev_chargers or not isinstance(ev_chargers, list):
        return config, changed

    # Find first enabled charger
    first_enabled: dict[str, Any] | None = None
    for item in cast("list[Any]", ev_chargers):
        if not isinstance(item, dict):
            continue
        ev = cast("dict[str, Any]", item)
        if ev.get("enabled", True):
            first_enabled = ev
            break

    if first_enabled is None:
        return config, changed

    # Migrate ev_departure_time -> departure_time
    old_departure = config.get("ev_departure_time", "")
    if old_departure and not first_enabled.get("departure_time"):
        first_enabled["departure_time"] = old_departure
        logger.info(
            f"🔄 Migrated ev_departure_time -> ev_chargers[0].departure_time: {old_departure}"
        )
        changed = True

    # Migrate executor.ev_charger settings
    executor_raw: Any = config.get("executor", {})
    if not isinstance(executor_raw, dict):
        return config, changed
    executor = cast("dict[str, Any]", executor_raw)
    ev_charger_exec_raw: Any = executor.get("ev_charger", {})
    if not isinstance(ev_charger_exec_raw, dict):
        return config, changed
    ev_charger_exec = cast("dict[str, Any]", ev_charger_exec_raw)

    # switch_entity
    old_switch: Any = ev_charger_exec.get("switch_entity", "")
    if old_switch and not first_enabled.get("switch_entity"):
        first_enabled["switch_entity"] = old_switch
        logger.info(
            f"🔄 Migrated executor.ev_charger.switch_entity -> ev_chargers[0].switch_entity: {old_switch}"
        )
        changed = True

    # replan_on_plugin (only migrate if key is absent in first_enabled)
    if "replan_on_plugin" not in first_enabled and "replan_on_plugin" in ev_charger_exec:
        first_enabled["replan_on_plugin"] = bool(ev_charger_exec["replan_on_plugin"])
        logger.info(
            f"🔄 Migrated executor.ev_charger.replan_on_plugin -> ev_chargers[0].replan_on_plugin: {first_enabled['replan_on_plugin']}"
        )
        changed = True

    # replan_on_unplug (only migrate if key is absent in first_enabled)
    if "replan_on_unplug" not in first_enabled and "replan_on_unplug" in ev_charger_exec:
        first_enabled["replan_on_unplug"] = bool(ev_charger_exec["replan_on_unplug"])
        logger.info(
            f"🔄 Migrated executor.ev_charger.replan_on_unplug -> ev_chargers[0].replan_on_unplug: {first_enabled['replan_on_unplug']}"
        )
        changed = True

    return config, changed


def _migrate_inverter_keys(config: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Migrate legacy system.inverter.max_power_kw to system.inverter.max_ac_power_kw.

    Reads system.inverter.max_power_kw (old key).
    If it exists AND system.inverter.max_ac_power_kw does NOT exist:
      - Set system.inverter.max_ac_power_kw to the old value

    Does NOT touch max_dc_input_kw (no old equivalent to migrate).

    Returns:
        Tuple of (modified_config, changed_flag)
    """
    changed = False
    system_raw: Any = config.get("system", {})
    if not isinstance(system_raw, dict):
        return config, changed
    system = cast("dict[str, Any]", system_raw)

    inverter_raw: Any = system.get("inverter", {})
    if not isinstance(inverter_raw, dict):
        return config, changed
    inverter = cast("dict[str, Any]", inverter_raw)

    old_max_power = inverter.get("max_power_kw")
    new_max_ac_power = inverter.get("max_ac_power_kw")

    if old_max_power is not None and new_max_ac_power is None:
        inverter["max_ac_power_kw"] = old_max_power
        logger.info(
            f"🔄 Migrated system.inverter.max_power_kw -> system.inverter.max_ac_power_kw: {old_max_power}"
        )
        changed = True

    return config, changed


def _remove_energy_sensor_fields(config: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Remove deprecated energy_sensor field from ev_chargers[] and water_heaters[] items.

    This field is no longer used — energy is now measured via the HA History API.

    Returns:
        Tuple of (modified_config, changed_flag)
    """
    changed = False
    for array_key in ("ev_chargers", "water_heaters"):
        for item in config.get(array_key, []):
            if isinstance(item, dict) and "energy_sensor" in item:
                del item["energy_sensor"]
                logger.info(f"✂️  Removed deprecated key: '{array_key}[].energy_sensor'")
                changed = True
    return config, changed


def _migrate_export_floor(config: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Migrate executor.override.low_soc_export_floor to export.export_floor_soc_percent.

    The export SoC floor moved from the executor override section to the export section,
    since it is now enforced by the planner (Kepler MILP) rather than the executor.

    Returns:
        Tuple of (modified_config, changed_flag)
    """
    changed = False

    executor_raw: Any = config.get("executor", {})
    if not isinstance(executor_raw, dict):
        return config, changed
    executor = cast("dict[str, Any]", executor_raw)

    override_raw: Any = executor.get("override", {})
    if not isinstance(override_raw, dict):
        return config, changed
    override = cast("dict[str, Any]", override_raw)

    old_value = override.get("low_soc_export_floor")
    if old_value is None:
        return config, changed

    export_section = config.get("export", {})
    if not isinstance(export_section, dict):
        export_section = {}
        config["export"] = export_section

    if "export_floor_soc_percent" not in export_section:
        export_section["export_floor_soc_percent"] = float(old_value)
        logger.info(
            f"🔄 Migrated executor.override.low_soc_export_floor -> export.export_floor_soc_percent: {old_value}"
        )
        changed = True

    if "low_soc_export_floor" in override:
        del override["low_soc_export_floor"]
        logger.info("✂️  Removed deprecated key: 'executor.override.low_soc_export_floor'")
        changed = True

    return config, changed


def _validate_config_structure(config: dict[str, Any], strict: bool = True) -> bool:
    """
    Validates that the config has minimum expected structure.
    Prevents merging empty/corrupted configs with defaults.

    Args:
        config: The configuration dict to validate
        strict: If True, requires full production config structure.
                If False, only validates basic structure (for tests/minimal configs).

    Returns True if config passes validation, False otherwise.
    """
    # Lenient mode: just ensure config is a non-empty dict with some keys
    if not strict:
        if len(config) == 0:
            logger.error("Config is empty")
            return False
        logger.debug("Config structure validation passed (lenient mode)")
        return True

    # Strict mode: full production validation
    system = config.get("system")
    if not isinstance(system, dict):
        logger.error("Config missing 'system' section")
        return False

    # Check for critical keys that indicate a valid user config
    # If these are missing, the config is likely empty/corrupted
    critical_keys = ["system_id", "inverter_profile", "has_solar", "has_battery"]
    missing_keys = [key for key in critical_keys if key not in system]

    if missing_keys:
        logger.error(f"Config missing critical keys in system section: {missing_keys}")
        return False

    # Additional check: verify location section exists (strong indicator of user config)
    location_raw: Any = system.get("location")  # type: ignore[reportUnknownMemberType]
    location: dict[str, Any] = (
        cast("dict[str, Any]", location_raw) if isinstance(location_raw, dict) else {}
    )
    if not location:
        logger.error("Config missing 'system.location' section")
        return False

    if "latitude" not in location or "longitude" not in location:
        logger.error("Config missing location coordinates")
        return False

    logger.debug("Config structure validation passed (strict mode)")
    return True


def validate_config_for_write(config: dict[str, Any], strict: bool = True) -> bool:
    """Enhanced validation before writing config to disk.

    Ensures no deprecated keys survive and structure is intact.

    Args:
        config: The configuration dict to validate
        strict: If True, requires full production config structure.
                If False, only validates basic structure (for tests/minimal configs).

    Returns:
        True if config is safe to write, False otherwise.
    """
    # Lenient mode: check for deprecated keys at all levels, allow minimal configs
    if not strict:
        # Check root-level deprecated keys
        for key in DEPRECATED_KEYS:
            if key in config:
                logger.error(f"❌ Validation failed: Deprecated key '{key}' still present")
                return False

        # Check nested deprecated keys
        for path, keys in DEPRECATED_NESTED_KEYS.items():
            parts = path.split(".")
            obj = config
            # Navigate to nested object
            for part in parts:
                if isinstance(obj, dict) and part in obj:
                    obj = obj[part]
                else:
                    break
            else:
                # Object exists, check deprecated keys
                if isinstance(obj, dict):
                    for key in keys:
                        if key in obj:
                            logger.error(
                                f"❌ Validation failed: Deprecated nested key '{path}.{key}' still present"
                            )
                            return False
        return True

    # Strict mode: full production validation
    # 1. Critical Sections
    required_sections = ["system", "battery", "executor", "input_sensors"]
    for section in required_sections:
        if section not in config:
            logger.error(f"❌ Validation failed: Missing required section '{section}'")
            return False

    # 2. Deprecated Keys (MUST be gone)
    for key in DEPRECATED_KEYS:
        if key in config:
            logger.error(f"❌ Validation failed: Deprecated key '{key}' still present")
            return False

    # 3. Version Position
    # config_version should be near the top
    keys = list(config.keys())
    if "config_version" in keys:
        idx = keys.index("config_version")
        if idx > 10:
            logger.error(f"❌ Validation failed: 'config_version' at index {idx} (too deep)")
            return False

    return True


def template_aware_merge(default_cfg: dict[str, Any], user_cfg: dict[str, Any]) -> None:
    """
    Uses default_cfg as the BASE (template).
    Overwrites values from user_cfg.
    Appends extra keys from user_cfg (recursively).
    Modifies default_cfg IN PLACE.

    Fixed array handling - merge arrays by unique ID instead of overwriting.
    """

    ARRAY_UNIQUE_KEYS = {
        "solar_arrays": "name",
        "water_heaters": "id",
        "ev_chargers": "id",
    }

    def merge_arrays(
        target_arr: list[dict[str, Any]], source_arr: list[dict[str, Any]], unique_key: str
    ) -> None:
        """Merge source array into target array by matching unique key.

        Strategy: Use user entries as base, merge in default fields for matched entries.
        - If user has entries: use user entries, but fill missing fields from defaults
        - If user has no entries: keep default entries
        """
        if not source_arr:
            # User has no entries, keep defaults
            return

        if not target_arr:
            # No defaults, use user's entries directly
            target_arr[:] = source_arr
            return

        # Build index of target items by unique_key (for default field lookup)
        target_by_key: dict[str, dict[str, Any]] = {}
        for target_item in target_arr:
            key_val_raw: Any = target_item.get(unique_key)
            key_val: str | None = str(key_val_raw) if key_val_raw is not None else None
            if key_val is not None:
                target_by_key[key_val] = target_item

        # Merge: source entries override, but preserve default fields from target
        result: list[dict[str, Any]] = []
        for source_item in source_arr:
            if not source_item:
                result.append(source_item)
                continue

            key_val_raw: Any = source_item.get(unique_key)
            key_str: str | None = str(key_val_raw) if key_val_raw is not None else None

            if key_str and key_str in target_by_key:
                # Merge: start with target's defaults, overlay source values
                merged: dict[str, Any] = dict(target_by_key[key_str])  # copy defaults
                merged.update(source_item)  # source overrides
                result.append(merged)
            else:
                # New entry from user, add as-is (no defaults to merge with)
                result.append(source_item)

        # DON'T add unmatched default entries - user entries replace entirely
        # (legacy migrations already created proper entries from old format)

        target_arr[:] = result

    def recursive_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
        for key, value in source.items():
            if key in target:
                target_val: Any = target[key]
                if isinstance(target_val, dict) and isinstance(value, dict):
                    recursive_merge(
                        cast("dict[str, Any]", target_val), cast("dict[str, Any]", value)
                    )
                elif isinstance(target_val, list) and isinstance(value, list):
                    unique_key = ARRAY_UNIQUE_KEYS.get(key)
                    if unique_key:
                        # Type safety: ensure lists contain dicts
                        target_list: list[dict[str, Any]] = [
                            cast("dict[str, Any]", item)
                            for item in cast("list[Any]", target_val)
                            if isinstance(item, dict)
                        ]
                        source_list: list[dict[str, Any]] = [
                            cast("dict[str, Any]", item)
                            for item in cast("list[Any]", value)
                            if isinstance(item, dict)
                        ]
                        merge_arrays(target_list, source_list, unique_key)
                        target[key] = target_list
                    else:
                        target[key] = value
                else:
                    target[key] = value
            else:
                target[key] = value

    recursive_merge(default_cfg, user_cfg)


def _extract_critical_values(config: dict[str, Any]) -> dict[str, Any]:
    """Extract critical user values that should never be lost."""
    system: dict[str, Any] = config.get("system", {})
    inverter_profile = system.get("inverter_profile")

    # Also check root level for misplaced inverter_profile
    if inverter_profile is None and "inverter_profile" in config:
        inverter_profile = config.get("inverter_profile")
        if inverter_profile:
            logger.warning(
                "Found 'inverter_profile' at root level instead of 'system.inverter_profile'. "
                "This may indicate a migration issue."
            )

    return {
        "inverter_profile": inverter_profile,
        "has_ev_charger": system.get("has_ev_charger"),
        "has_water_heater": system.get("has_water_heater"),
        "latitude": system.get("location", {}).get("latitude"),
        "longitude": system.get("location", {}).get("longitude"),
        "solar_arrays_count": len(system.get("solar_arrays", [])),
        "min_soc": config.get("battery", {}).get("min_soc_percent"),
    }


def _validate_critical_values_preserved(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """
    Verify that critical user values were preserved during merge.
    Returns True if all values are preserved, False otherwise.
    """
    critical_keys = [
        "inverter_profile",
        "has_ev_charger",
        "has_water_heater",
        "latitude",
        "longitude",
        "solar_arrays_count",
        "min_soc",
    ]

    issues: list[str] = []
    for key in critical_keys:
        before_val = before.get(key)
        after_val = after.get(key)

        # Skip if value was None before (not set)
        if before_val is None:
            continue

        # Check if value changed to a default
        if after_val != before_val:
            # Special case: allow solar_arrays_count to increase (adding default arrays)
            if key == "solar_arrays_count" and (after_val or 0) > (before_val or 0):
                continue
            issues.append(f"{key}: {before_val} -> {after_val}")

    if issues:
        logger.error(f"❌ CRITICAL VALUES LOST DURING MIGRATION: {', '.join(issues)}")
        return False

    return True


async def migrate_config(
    config_path: str = "config.yaml",
    default_path: str = "config.default.yaml",
    strict_validation: bool = True,
) -> None:
    """
    Run config migration at startup.
    Uses ruamel.yaml to preserve comments and structure.

    Args:
        config_path: Path to the user config file
        default_path: Path to the default config template
        strict_validation: If True, requires full production config structure.
                          If False, allows minimal configs (for tests).
    """
    path = Path(config_path)
    if not path.exists():
        logger.debug(f"Config file {config_path} not found, skipping migration")
        return

    if YAML is None:
        logger.warning(
            "ruamel.yaml not installed, skipping auto-migration. Please update config manually."
        )
        return

    # 1. Load User Config
    try:
        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)
        yaml.width = 4096

        with path.open("r", encoding="utf-8") as f:
            user_config_raw = yaml.load(f)  # type: ignore[reportUnknownMemberType]

        if user_config_raw is None or not isinstance(user_config_raw, dict):
            logger.error(f"❌ Config {config_path} is invalid or empty.")
            return
        user_config: dict[str, Any] = cast("dict[str, Any]", user_config_raw)

        # SAFETY CHECK: Verify config has minimum expected structure
        # This prevents merging an empty/corrupted config with defaults
        if not _validate_config_structure(user_config, strict=strict_validation):
            logger.error(
                f"❌ Config {config_path} failed structure validation. Aborting migration to prevent data loss."
            )
            return

    except Exception as e:
        logger.error(f"❌ Failed to read user config: {e}")
        return

    # 2. Migrate fields that read deprecated keys BEFORE removing them
    # 2.1 Migrate global EV charger fields into per-device ev_chargers[] entries
    user_config, ev_migration_changes = _migrate_ev_charger_fields(user_config)
    pre_merge_changes = ev_migration_changes

    # 2.1b Migrate inverter config keys (must run before remove_deprecated_keys)
    user_config, inverter_migration_changes = _migrate_inverter_keys(user_config)
    if inverter_migration_changes:
        pre_merge_changes = True

    # 2.2 Sweep deprecated keys from user config
    user_config, deprecated_changes = remove_deprecated_keys(user_config)
    if deprecated_changes:
        pre_merge_changes = True

    # 2.5 Migrate water heater fields (must run after remove_deprecated_keys, before template merge)
    user_config, migration_changes = _migrate_water_heater_fields(user_config)
    if migration_changes:
        pre_merge_changes = True

    # 2.7 Migrate export floor from executor.override to export section
    user_config, export_floor_changes = _migrate_export_floor(user_config)
    if export_floor_changes:
        pre_merge_changes = True

    # 2.6 Remove energy_sensor from ev_chargers[] and water_heaters[]
    user_config, energy_sensor_changes = _remove_energy_sensor_fields(user_config)
    if energy_sensor_changes:
        pre_merge_changes = True

    # 2.8 Ensure config_version is at least CURRENT_CONFIG_VERSION.
    # Runs independently of the template merge so the version is always set.
    # Never downgrades a version that is already higher.
    current_version = user_config.get("config_version")
    if not isinstance(current_version, int) or current_version < CURRENT_CONFIG_VERSION:
        user_config["config_version"] = CURRENT_CONFIG_VERSION
        pre_merge_changes = True

    # 3. Load Default Config (The Template)
    def_path_obj = Path(default_path)
    if not def_path_obj.exists():
        logger.warning(f"{default_path} not found. Skipping template merge.")
        if pre_merge_changes:
            _write_config(path, user_config, yaml, strict_validation=strict_validation)
        return

    try:
        with def_path_obj.open("r", encoding="utf-8") as f:
            default_config_raw = yaml.load(f)  # type: ignore[reportUnknownMemberType]
        if default_config_raw is None or not isinstance(default_config_raw, dict):
            logger.error(f"❌ Default config {default_path} is invalid or empty.")
            if pre_merge_changes:
                _write_config(path, user_config, yaml, strict_validation=strict_validation)
            return
        default_config: dict[str, Any] = cast("dict[str, Any]", default_config_raw)
    except Exception as e:
        logger.error(f"❌ Failed to read default config: {e}")
        if pre_merge_changes:
            _write_config(path, user_config, yaml, strict_validation=strict_validation)
        return

    # 4. Perform Template Merge
    # Merge user values into the template structure
    try:
        # Capture user config as serialized string to detect structural changes after merge
        user_str_buf = io.StringIO()
        yaml.dump(user_config, user_str_buf)  # type: ignore[reportUnknownMemberType]
        user_str_before = user_str_buf.getvalue()

        final_config: dict[str, Any] = default_config

        # CAPTURE CRITICAL VALUES BEFORE MERGE
        critical_before = _extract_critical_values(user_config)
        logger.debug(f"Critical values before merge: {critical_before}")

        template_aware_merge(final_config, user_config)

        # Final cleanup - remove any deprecated keys that survived the merge
        final_config, cleanup_changed = remove_deprecated_keys(final_config)
        if cleanup_changed:
            logger.info("✅ Final deprecated keys cleanup successful")

        # VALIDATE CRITICAL VALUES AFTER MERGE
        critical_after = _extract_critical_values(final_config)
        logger.debug(f"Critical values after merge: {critical_after}")

        if not _validate_critical_values_preserved(critical_before, critical_after):
            logger.error("❌ CRITICAL CONFIG VALUES WOULD BE LOST! Aborting migration.")
            logger.error("This usually means the user config failed to load properly.")
            logger.error(f"Please check {config_path} for corruption or file locks.")
            return

        # 5. Save if anything changed (deprecated keys removed, or structure differs from template)
        final_str_buf = io.StringIO()
        yaml.dump(final_config, final_str_buf)  # type: ignore[reportUnknownMemberType]
        structure_changed = final_str_buf.getvalue() != user_str_before

        if pre_merge_changes or cleanup_changed or structure_changed:
            _write_config(path, final_config, yaml, strict_validation=strict_validation)

    except Exception as e:
        logger.error(f"❌ Template merge failed: {e}", exc_info=True)


def create_timestamped_backup(path: Path, max_backups: int = 30) -> Path | None:
    """Create a timestamped backup of the file, pruning old ones. Returns backup path or None."""
    if not path.exists():
        return None

    try:
        backup_dir = _get_persistent_backup_dir(path)
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{path.name}_{timestamp}.bak"

        shutil.copy2(path, backup_path)
        logger.info(f"💾 Created timestamped backup: {backup_path.name}")

        # Retention logic
        backups = sorted(
            backup_dir.glob(f"{path.name}_*.bak"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if len(backups) > max_backups:
            for old_backup in backups[max_backups:]:
                old_backup.unlink()
                logger.info(f"🧹 Cleaned up old backup: {old_backup.name}")

        return backup_path
    except Exception as e:
        logger.error(f"❌ Failed to create backup: {e}")
        return None


def write_config(
    path: Path, config: Any, yaml_instance: Any, strict_validation: bool = True
) -> bool:
    """Public wrapper for the shared config writer."""
    return _write_config(path, config, yaml_instance, strict_validation=strict_validation)


def _write_config(
    path: Path, config: Any, yaml_instance: Any, strict_validation: bool = True
) -> bool:
    """Validate and atomically write config to disk with timestamped backup.

    Returns True if the write succeeded, False if aborted or failed.
    """
    if not validate_config_for_write(config, strict=strict_validation):
        logger.error(f"❌ Aborting write to {path} - validation failed.")
        return False

    temp_path = path.with_name(path.name + ".tmp")
    legacy_backup_path = path.with_name(path.name + ".bak")
    log_prefix = "[CONTAINER]" if Path("/.dockerenv").exists() else "[HOST]"
    success = False

    try:
        if path.exists():
            create_timestamped_backup(path)
            shutil.copy2(path, legacy_backup_path)

        logger.info(f"{log_prefix} Writing updated config to {temp_path}")
        with temp_path.open("w", encoding="utf-8") as f:
            yaml_instance.dump(config, f)

        # Atomic Replace
        try:
            temp_path.replace(path)
            logger.info(f"✅ {log_prefix} Successfully updated {path} (Atomic)")

            # Post-write validation - verify written file is valid
            success = _verify_written_config(path, yaml_instance)

        except OSError as e:
            # Fallback for bind mounts (EBUSY/EXDEV/ETXTBSY).
            # temp_path is already in path's directory (path.with_name), so retry
            # os.replace within the same mount first — keeps the rename atomic.
            if e.errno in (errno.EBUSY, errno.EXDEV, errno.ETXTBSY):
                logger.info(
                    f"{log_prefix} Bind mount detected, retrying atomic replace within directory."
                )
                try:
                    temp_path.replace(path)
                    logger.info(f"✅ {log_prefix} Successfully updated {path} (Atomic retry)")
                    success = _verify_written_config(path, yaml_instance)
                except OSError:
                    # Last resort: fsync before and after the streaming copy so a
                    # partial copy is at least durable if the process dies mid-copy.
                    logger.warning(
                        f"⚠️ {log_prefix} Atomic replace not possible on this mount, "
                        f"falling back to direct copy (last resort)."
                    )
                    with temp_path.open("rb") as _f:
                        os.fsync(_f.fileno())
                    shutil.copy2(temp_path, path)
                    with path.open("rb") as _f:
                        os.fsync(_f.fileno())
                    logger.info(
                        f"✅ {log_prefix} Successfully updated {path} (Direct Copy, fsynced)"
                    )
                    success = _verify_written_config(path, yaml_instance)
            else:
                raise

    except Exception as e:
        logger.error(f"❌ Write failed: {e}")
        if legacy_backup_path.exists():
            logger.warning(f"🔄 Restoring {path} from legacy backup...")
            shutil.copy2(legacy_backup_path, path)
    finally:
        with contextlib.suppress(Exception):
            if temp_path.exists():
                temp_path.unlink()

    return success


def _verify_written_config(path: Path, yaml_instance: Any) -> bool:
    """Read back the written config and verify it is valid. Returns True if valid."""
    try:
        with path.open("r", encoding="utf-8") as f:
            loaded = yaml_instance.load(f)

        if loaded is None or not isinstance(loaded, dict):
            logger.error("❌ Post-write validation failed: config is empty or not a dict")
            return False
        loaded_dict: dict[str, Any] = cast("dict[str, Any]", loaded)

        # Check for basic expected structure
        if "system" not in loaded_dict:
            logger.error("❌ Post-write validation failed: missing 'system' section")
            return False

        # Check inverter_profile is in correct location
        system: dict[str, Any] = loaded_dict.get("system", {})
        if "inverter_profile" not in system:
            if "inverter_profile" in loaded:
                logger.warning(
                    "⚠️  Post-write: 'inverter_profile' found at root level, "
                    "should be under 'system'. This may cause issues."
                )
            else:
                logger.warning("⚠️  Post-write: 'inverter_profile' not found in config")

        logger.debug("✅ Post-write config validation passed")
        return True

    except Exception as e:
        logger.error(f"❌ Post-write validation failed: {e}")
        return False


if __name__ == "__main__":
    import asyncio

    # Setup basic logging for standalone run
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(migrate_config())
