"""
Inverter Profile System v2

Declarative, profile-driven architecture where each mode defines an ordered
list of entity+value actions. The executor is a generic loop.

Schema Version: 2
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

VALID_DOMAINS = frozenset(["select", "number", "switch", "input_number", "input_datetime"])
VALID_CATEGORIES = frozenset(["system", "battery"])
VALID_TEMPLATES = frozenset(
    [
        "charge_value",
        "discharge_value",
        "soc_target",
        "export_power_w",
        "export_with_load_w",
        "max_charge",
        "max_discharge",
    ]
)
REQUIRED_MODES = frozenset(["charge", "export", "self_consumption", "idle"])


class ProfileError(Exception):
    """Raised when a profile has invalid configuration."""

    pass


@dataclass
class EntityDefinition:
    """A single entity in the profile's entity registry."""

    default_entity: str | None
    domain: str
    category: str
    description: str
    required: bool = True


@dataclass
class ModeAction:
    """A single action within a mode definition."""

    entity: str
    value: str | int | float | bool
    settle_ms: int | None = None


@dataclass
class ModeDefinition:
    """A complete mode definition with ordered actions."""

    description: str
    actions: list[ModeAction] = field(default_factory=list[ModeAction])


@dataclass
class ProfileBehavior:
    """Executor behavior parameters."""

    control_unit: str = "A"
    min_charge_a: float = 1.0
    min_charge_w: float = 10.0
    round_step_a: float = 1.0
    round_step_w: float = 100.0
    grid_charge_round_step_w: float | None = None
    write_threshold_w: float = 100.0
    mode_settling_ms: int = 100
    requires_mode_settling: bool = False


@dataclass
class ProfileMetadata:
    """Profile metadata."""

    name: str
    version: str
    schema_version: int = 1
    description: str = ""
    supported_brands: list[str] = field(default_factory=list[str])


@dataclass
class InverterProfile:
    """Complete v2 inverter profile.

    Uses entity registry + mode action lists architecture.
    Each mode defines an ordered list of entity+value pairs.
    """

    metadata: ProfileMetadata
    entities: dict[str, EntityDefinition] = field(default_factory=dict[str, EntityDefinition])
    modes: dict[str, ModeDefinition] = field(default_factory=dict[str, ModeDefinition])
    behavior: ProfileBehavior = field(default_factory=ProfileBehavior)

    def get_mode(self, mode_intent: str) -> ModeDefinition:
        """Get mode definition by intent key. Raises ProfileError if not found."""
        if mode_intent not in self.modes:
            raise ProfileError(
                f"Mode '{mode_intent}' not defined in profile '{self.metadata.name}'"
            )
        return self.modes[mode_intent]

    def get_entity(self, key: str) -> EntityDefinition:
        """Get entity definition by key. Raises ProfileError if not found."""
        if key not in self.entities:
            raise ProfileError(f"Entity '{key}' not defined in profile '{self.metadata.name}'")
        return self.entities[key]

    def get_required_entities(self) -> dict[str, EntityDefinition]:
        """Return all required entities."""
        return {k: v for k, v in self.entities.items() if v.required}

    def get_entities_by_category(self, category: str) -> dict[str, EntityDefinition]:
        """Return all entities in a specific category."""
        return {k: v for k, v in self.entities.items() if v.category == category}

    def get_missing_entities(self, config: dict[str, Any]) -> list[str]:
        """
        Check config for missing required entities.

        Returns list of missing entity keys (not full config paths).
        Uses entity resolution order: user override > standard config > profile default.
        """
        missing: list[str] = []

        for key, entity_def in self.entities.items():
            if not entity_def.required:
                continue

            resolved = _resolve_entity_id_from_config(key, config)
            if not resolved and entity_def.default_entity is None:
                missing.append(key)

        return missing

    def validate(self) -> tuple[bool, list[str]]:
        """
        Validate the profile for completeness and correctness.

        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors: list[str] = []

        if self.metadata.schema_version != 2:
            errors.append(f"Invalid schema_version: {self.metadata.schema_version}. Must be 2.")

        if not self.metadata.name:
            errors.append("Profile metadata.name is required")

        if not self.metadata.version:
            errors.append("Profile metadata.version is required")

        if self.behavior.control_unit not in ("A", "W", None):
            errors.append(
                f"Invalid control_unit: {self.behavior.control_unit}. Must be 'A', 'W', or null"
            )

        for mode_name in REQUIRED_MODES:
            if mode_name not in self.modes:
                errors.append(f"Missing required mode: {mode_name}")
            elif not self.modes[mode_name].actions:
                errors.append(f"Mode '{mode_name}' has no actions defined")

        for key, entity_def in self.entities.items():
            if entity_def.domain not in VALID_DOMAINS:
                errors.append(f"Entity '{key}' has invalid domain: {entity_def.domain}")
            if entity_def.category not in VALID_CATEGORIES:
                errors.append(f"Entity '{key}' has invalid category: {entity_def.category}")

        for mode_key, mode_def in self.modes.items():
            for action in mode_def.actions:
                if action.entity not in self.entities:
                    errors.append(
                        f"Mode '{mode_key}': action references unknown entity '{action.entity}'"
                    )

                if isinstance(action.value, str) and action.value.startswith("{{"):
                    template = action.value[2:-2]
                    if template not in VALID_TEMPLATES:
                        errors.append(
                            f"Mode '{mode_key}': action uses unknown template '{{{{{template}}}}}'"
                        )

        return len(errors) == 0, errors


def _resolve_entity_id_from_config(key: str, config: dict[str, Any]) -> str | None:
    """
    Resolve entity key to actual HA entity ID from config.

    Resolution order:
    1. User override: executor.inverter.custom_entities[key]
    2. Standard config: executor.inverter[key]
    3. None if not found
    """
    executor_config: dict[str, Any] = config.get("executor", {})
    inverter_config: dict[str, Any] = executor_config.get("inverter", {})

    custom_entities: dict[str, Any] = inverter_config.get("custom_entities", {})
    override: str | None = custom_entities.get(key)
    if override:
        return override

    standard: str | None = inverter_config.get(key)
    if standard:
        return standard

    return None


def load_profile_yaml(profile_path: Path) -> dict[str, Any]:
    """
    Load profile YAML file.

    Args:
        profile_path: Path to the profile YAML file

    Returns:
        Parsed YAML dict

    Raises:
        FileNotFoundError: If profile file doesn't exist
        yaml.YAMLError: If YAML is malformed
    """
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile file not found: {profile_path}")

    with profile_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data:
        raise ValueError(f"Profile file is empty: {profile_path}")

    return data


def _parse_entity(key: str, data: dict[str, Any]) -> EntityDefinition:
    """Parse a single entity definition from YAML data."""
    return EntityDefinition(
        default_entity=data.get("default_entity"),
        domain=data.get("domain", "select"),
        category=data.get("category", "system"),
        description=data.get("description", ""),
        required=data.get("required", True),
    )


def _parse_mode_action(data: dict[str, Any]) -> ModeAction:
    """Parse a single mode action from YAML data."""
    raw_value: Any = data.get("value")
    value: str | int | float | bool
    if raw_value is None:  # noqa: SIM108
        value = ""
    else:
        value = raw_value
    return ModeAction(
        entity=data.get("entity", ""),
        value=value,
        settle_ms=data.get("settle_ms"),
    )


def _parse_mode_definition(data: dict[str, Any]) -> ModeDefinition:
    """Parse a complete mode definition from YAML data."""
    actions: list[ModeAction] = []
    for action_data in data.get("actions", []):
        actions.append(_parse_mode_action(action_data))

    return ModeDefinition(
        description=data.get("description", ""),
        actions=actions,
    )


def parse_profile(data: dict[str, Any]) -> InverterProfile:
    """
    Parse profile data into InverterProfile dataclass.

    Args:
        data: Profile YAML data

    Returns:
        InverterProfile instance

    Raises:
        ValueError: If required fields are missing
    """
    metadata_data = data.get("metadata", {})
    metadata = ProfileMetadata(
        name=metadata_data.get("name", "unknown"),
        version=metadata_data.get("version", "1.0.0"),
        schema_version=metadata_data.get("schema_version", 1),
        description=metadata_data.get("description", ""),
        supported_brands=metadata_data.get("supported_brands", []),
    )

    entities: dict[str, EntityDefinition] = {}
    entities_data = data.get("entities", {})
    for key, entity_data in entities_data.items():
        entities[key] = _parse_entity(key, entity_data)

    modes: dict[str, ModeDefinition] = {}
    modes_data = data.get("modes", {})
    for key, mode_data in modes_data.items():
        modes[key] = _parse_mode_definition(mode_data)

    behavior_data = data.get("behavior", {})
    behavior = ProfileBehavior(
        control_unit=behavior_data.get("control_unit", "A"),
        min_charge_a=behavior_data.get("min_charge_a", 1.0),
        min_charge_w=behavior_data.get("min_charge_w", 10.0),
        round_step_a=behavior_data.get("round_step_a", 1.0),
        round_step_w=behavior_data.get("round_step_w", 100.0),
        grid_charge_round_step_w=behavior_data.get("grid_charge_round_step_w"),
        write_threshold_w=behavior_data.get("write_threshold_w", 100.0),
        mode_settling_ms=behavior_data.get("mode_settling_ms", 100),
    )

    return InverterProfile(
        metadata=metadata,
        entities=entities,
        modes=modes,
        behavior=behavior,
    )


def load_profile(profile_name: str, profiles_dir: str | Path = "profiles") -> InverterProfile:
    """
    Load an inverter profile by name.

    Args:
        profile_name: Name of the profile (e.g., "deye", "fronius", "generic")
        profiles_dir: Directory containing profile YAML files

    Returns:
        InverterProfile instance

    Raises:
        FileNotFoundError: If profile file doesn't exist
        ValueError: If profile is invalid
    """
    profiles_path = Path(profiles_dir)
    profile_file = profiles_path / f"{profile_name}.yaml"

    logger.info("Loading inverter profile: %s from %s", profile_name, profile_file)

    try:
        data = load_profile_yaml(profile_file)
    except FileNotFoundError:
        logger.error("Profile file not found: %s", profile_file)
        raise
    except yaml.YAMLError as e:
        logger.error("Failed to parse profile YAML: %s", e)
        raise ValueError(f"Invalid YAML in profile {profile_name}: {e}") from e

    try:
        profile = parse_profile(data)
    except Exception as e:
        logger.exception("Failed to parse profile data for profile %s", profile_name)
        raise ValueError(f"Failed to parse profile {profile_name}: {e}") from e

    is_valid, errors = profile.validate()
    if not is_valid:
        error_msg = f"Profile {profile_name} validation failed: {', '.join(errors)}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    logger.info(
        "Profile loaded successfully: %s v%s (schema v%d, %s)",
        profile.metadata.name,
        profile.metadata.version,
        profile.metadata.schema_version,
        ", ".join(profile.metadata.supported_brands) or "generic",
    )

    return profile


def get_profile_from_config(
    config: dict[str, Any], profiles_dir: str | Path = "profiles"
) -> InverterProfile:
    """
    Load profile based on config setting with fallback to generic.

    Args:
        config: Full config dictionary with system.inverter_profile setting
        profiles_dir: Directory containing profile YAML files

    Returns:
        InverterProfile instance
    """
    system_config = config.get("system", {})
    profile_name = system_config.get("inverter_profile", "generic")

    logger.info("Loading inverter profile from config: %s", profile_name)

    try:
        return load_profile(profile_name, profiles_dir)
    except FileNotFoundError:
        logger.warning("Profile '%s' not found, falling back to 'generic' profile", profile_name)
        return load_profile("generic", profiles_dir)
    except Exception as e:
        logger.error("Failed to load profile '%s': %s. Falling back to 'generic'", profile_name, e)
        return load_profile("generic", profiles_dir)


def list_profiles(profiles_dir: str | Path = "profiles") -> list[dict[str, Any]]:
    """
    List all available profiles in the profiles directory.

    Returns:
        List of profile metadata dictionaries
    """
    profiles_path = Path(profiles_dir)
    profiles: list[dict[str, Any]] = []

    if not profiles_path.exists():
        logger.warning("Profiles directory not found: %s", profiles_path)
        return []

    for yaml_file in profiles_path.glob("*.yaml"):
        if yaml_file.name == "schema.yaml":
            continue

        try:
            profile = load_profile(yaml_file.stem, profiles_dir)
            profiles.append(
                {
                    "name": profile.metadata.name,
                    "description": profile.metadata.description,
                    "supported_brands": profile.metadata.supported_brands,
                    "version": profile.metadata.version,
                    "schema_version": profile.metadata.schema_version,
                    "entities": {
                        k: {
                            "default_entity": v.default_entity,
                            "domain": v.domain,
                            "category": v.category,
                            "description": v.description,
                            "required": v.required,
                        }
                        for k, v in profile.entities.items()
                    },
                    "modes": {
                        k: {
                            "description": v.description,
                            "action_count": len(v.actions),
                        }
                        for k, v in profile.modes.items()
                    },
                    "behavior": {
                        "control_unit": profile.behavior.control_unit,
                    },
                }
            )
        except Exception as e:
            logger.error("Skipping invalid profile %s: %s", yaml_file.name, e)

    return sorted(profiles, key=lambda x: x["name"])
