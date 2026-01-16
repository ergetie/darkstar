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


# List of migrations to run in order
MIGRATIONS: list[MigrationStep] = [
    migrate_battery_config,
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
