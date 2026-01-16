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
        if "version" in default_config:
            if config.get("version") != default_config["version"]:
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


# List of migrations to run in order
MIGRATIONS: list[MigrationStep] = [
    migrate_battery_config,
    soft_merge_defaults,
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
