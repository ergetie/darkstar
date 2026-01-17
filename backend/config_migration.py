import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    from ruamel.yaml import YAML
except ImportError:
    # Fallback if ruamel.yaml is not available (should be in requirements.txt)
    YAML = None

logger = logging.getLogger("darkstar.config_migration")

# Type alias for migration functions
MigrationStep = Callable[[Any], bool]


def migrate_battery_config(config: Any) -> bool:
    """
    Migration for REV F17: Unify Battery & Control Configuration.
    Moves hardware limits from executor.controller to root battery section.
    """
    changed = False

    # Target section
    if "battery" not in config:
        config["battery"] = {}
    battery = config["battery"]

    # Source section
    executor = config.get("executor", {})
    controller = executor.get("controller", {})

    if not controller:
        return False

    # Mapping of (Legacy Key, New Key)
    mapping = {
        "battery_capacity_kwh": "capacity_kwh",
        "system_voltage_v": "nominal_voltage_v",
        "worst_case_voltage_v": "min_voltage_v",
        "max_charge_a": "max_charge_a",
        "max_discharge_a": "max_discharge_a",
        "max_charge_w": "max_charge_w",
        "max_discharge_w": "max_discharge_w",
    }

    for legacy_key, new_key in mapping.items():
        if legacy_key in controller:
            val = controller.pop(legacy_key)

            # Only set if not already present in target (preserve existing battery settings if any)
            # OR if it was the redundant battery_capacity_kwh which we want to unify
            if new_key not in battery or legacy_key == "battery_capacity_kwh":
                battery[new_key] = val
                logger.info(f"Migrated {legacy_key} -> battery.{new_key}")
                changed = True
            else:
                logger.info(f"Removed legacy {legacy_key} (already exists in battery.{new_key})")
                changed = True

    # Cleanup empty controller section if needed (optional)
    # if not controller:
    #    del executor["controller"]

    return changed


def soft_merge_defaults(config: Any) -> bool:
    """
    Migration for REV F18: Soft Merge Defaults & Version Sync.
    Recursively fills missing keys from config.default.yaml into user config.
    Also updates the 'version' field to match defaults.
    """
    changed = False
    default_path = Path("config.default.yaml")

    if not default_path.exists():
        logger.warning("config.default.yaml not found, skipping soft merge.")
        return False

    try:
        if YAML is None:
            logger.warning("ruamel.yaml not installed, skipping soft merge.")
            return False

        yaml = YAML()
        with default_path.open("r", encoding="utf-8") as f:
            default_config = yaml.load(f)

        if not default_config:
            return False

        # 1. Sync Version (Always update to match default)
        if "version" in default_config and config.get("version") != default_config["version"]:
            # If key exists, update it. If not, insert at top.
            if "version" in config:
                config["version"] = default_config["version"]
            else:
                config.insert(0, "version", default_config["version"])
            logger.info(f"Updated config version to {default_config['version']}")
            changed = True

        # 2. Recursive Soft Merge
        def recursive_merge(user_node: dict, default_node: dict, path: str = "") -> bool:
            node_changed = False
            for key, default_val in default_node.items():
                current_path = f"{path}.{key}" if path else key

                if key not in user_node:
                    # Key missing in user config -> Copy from default
                    user_node[key] = default_val
                    logger.info(f"Added missing key: {current_path}")
                    node_changed = True
                elif isinstance(user_node[key], dict) and isinstance(default_val, dict):
                    # Both are dicts -> Recurse
                    if recursive_merge(user_node[key], default_val, current_path):
                        node_changed = True
                # Else: Key exists and is not a dict (or type mismatch) -> Keep user value (Safe)

            return node_changed

        if recursive_merge(config, default_config):
            changed = True

    except Exception as e:
        logger.error(f"Soft merge failed: {e}")

    return changed


def cleanup_obsolete_keys(config: Any) -> bool:
    """
    Migration for REV F19: Cleanup obsolete keys and move end_date.
    Matches the actual observed nesting in config.yaml.
    """
    changed = False

    # 1. Remove schedule_future_only (could be at root or under water_heating)
    if "schedule_future_only" in config:
        config.pop("schedule_future_only")
        logger.info("Removed root level obsolete key: schedule_future_only")
        changed = True

    if (
        "water_heating" in config
        and isinstance(config["water_heating"], dict)
        and "schedule_future_only" in config["water_heating"]
    ):
        config["water_heating"].pop("schedule_future_only")
        logger.info("Removed water_heating level obsolete key: schedule_future_only")
        changed = True

    # 2. Re-anchor end_date if it is "leaking" past comments
    # In config.yaml it was found under vacation_mode but after the S-Index comment.
    # We want to ensure it is grouped with other vacation_mode keys.
    # To do this, we can pop and re-insert if we detect it's misplaced,
    # but ruamel.yaml handles ordering during dump if we sort or re-insert.

    # First, find where it is
    end_date_val = None
    source_parent = None

    if "end_date" in config:
        end_date_val = config.pop("end_date")
        source_parent = "root"
    elif "water_heating" in config and isinstance(config["water_heating"], dict):
        wh = config["water_heating"]
        if "end_date" in wh:
            end_date_val = wh.pop("end_date")
            source_parent = "water_heating"
        elif "vacation_mode" in wh and isinstance(wh["vacation_mode"], dict):
            vm = wh["vacation_mode"]
            if "end_date" in vm:
                # It is already there! But is it misplaced (after comment)?
                # Popping and re-inserting will usually put it at the end,
                # which might still be after the comment if the comment is a 'leaf' comment.
                end_date_val = vm.pop("end_date")
                source_parent = "vacation_mode"

    if end_date_val is not None:
        if "water_heating" not in config:
            config["water_heating"] = {}
        if "vacation_mode" not in config["water_heating"]:
            config["water_heating"]["vacation_mode"] = {}

        # Re-inserting will put it at the end of vacation_mode.
        # This is fine as long as we don't have that leaking comment as a footer.
        config["water_heating"]["vacation_mode"]["end_date"] = end_date_val
        logger.info(f"Re-aligned end_date to vacation_mode from {source_parent}")
        changed = True

    return changed


# List of migrations to run in order
MIGRATIONS: list[MigrationStep] = [
    migrate_battery_config,
    soft_merge_defaults,
    cleanup_obsolete_keys,
]


async def migrate_config(config_path: str = "config.yaml") -> None:
    """
    Run all registered config migrations.
    Uses ruamel.yaml to preserve comments and structure.
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

    try:
        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)
        # Prevent wrapping of long lines (like entity IDs)
        yaml.width = 4096

        with path.open("r", encoding="utf-8") as f:
            config = yaml.load(f)

        if config is None:
            return

        any_changed = False
        for step in MIGRATIONS:
            if step(config):
                any_changed = True

        if any_changed:
            # Write back atomically
            temp_path = path.with_suffix(".tmp")
            with temp_path.open("w", encoding="utf-8") as f:
                yaml.dump(config, f)

            # Backup original if not already backed up today?
            # For simplicity, just replace.
            temp_path.replace(path)
            logger.info(f"✅ Successfully migrated {config_path} to newest version structure")
        else:
            logger.debug("Config is already up to date")

    except Exception as e:
        logger.error(f"❌ Failed to migrate config: {e}", exc_info=True)
