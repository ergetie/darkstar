"""Shared sender-side contract for installation statistics."""

from __future__ import annotations

import os
import platform
import uuid
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import urlsplit

DEFAULT_INSTALLATION_STATS_ENDPOINT = "https://telemetry.wxl.se/api/ping"
BUILT_IN_INVERTER_PROFILES = frozenset({"deye", "fronius", "generic", "sungrow"})
RELEASE_CHANNELS = frozenset({"stable", "dev", "unknown"})
INSTALLATION_TYPES = frozenset({"ha_addon", "docker", "unknown"})
ARCHITECTURES = frozenset({"amd64", "aarch64", "unknown"})
EXECUTION_MODES = frozenset({"shadow", "live", "unknown"})
PAYLOAD_FIELDS = frozenset(
    {
        "installation_id",
        "version",
        "release_channel",
        "installation_type",
        "architecture",
        "inverter_profile",
        "execution_mode",
    }
)


def is_valid_telemetry_endpoint(value: object) -> bool:
    """Return whether value is an absolute HTTPS URL without credentials or extras."""
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\\" in value
        or any(
            character.isspace() or ord(character) < 0x21 or ord(character) == 0x7F
            for character in value
        )
    ):
        return False
    try:
        parsed = urlsplit(value)
        # Accessing port validates malformed and out-of-range port numbers.
        _ = parsed.port
        return (
            parsed.scheme.lower() == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


def effective_installation_stats(config: Mapping[str, Any]) -> dict[str, Any]:
    """Fill omitted reporting settings without replacing explicit saved values."""
    if "installation_stats" not in config:
        raw: Any = {}
    else:
        raw = config["installation_stats"]
    if not isinstance(raw, Mapping):
        return {"enabled": raw, "endpoint": DEFAULT_INSTALLATION_STATS_ENDPOINT}
    settings = cast("Mapping[str, Any]", raw)
    return {
        "enabled": settings.get("enabled", True),
        "endpoint": settings.get("endpoint", DEFAULT_INSTALLATION_STATS_ENDPOINT),
    }


def classify_release_channel(value: object | None = None) -> str:
    """Use explicit image metadata; source checkouts without it stay unknown."""
    candidate = value if value is not None else os.getenv("DARKSTAR_RELEASE_CHANNEL")
    return candidate if isinstance(candidate, str) and candidate in RELEASE_CHANNELS else "unknown"


def classify_installation_type(value: object | None = None) -> str:
    candidate = value if value is not None else os.getenv("DARKSTAR_INSTALLATION_TYPE")
    return (
        candidate if isinstance(candidate, str) and candidate in INSTALLATION_TYPES else "unknown"
    )


def normalize_architecture(value: object | None = None) -> str:
    candidate = value if value is not None else os.getenv("DARKSTAR_ARCH")
    if candidate is None or candidate == "":
        candidate = platform.machine()
    aliases = {
        "amd64": "amd64",
        "x86_64": "amd64",
        "x86-64": "amd64",
        "x64": "amd64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
        "arm64v8": "aarch64",
    }
    return (
        aliases.get(candidate.strip().lower(), "unknown")
        if isinstance(candidate, str)
        else "unknown"
    )


def classify_inverter_profile(config: Mapping[str, Any]) -> str:
    system = config.get("system")
    system_config: Mapping[str, Any] = (
        cast("Mapping[str, Any]", system) if isinstance(system, Mapping) else {}
    )
    profile: object = system_config.get("inverter_profile")
    if profile is None or profile == "":
        return "unknown"
    if not isinstance(profile, str):
        return "unknown"
    return (
        profile.strip().lower()
        if profile.strip().lower() in BUILT_IN_INVERTER_PROFILES
        else "custom"
    )


def classify_execution_mode(config: Mapping[str, Any]) -> str:
    """Map the configured executor flag without coercing missing or malformed values."""
    executor = config.get("executor")
    if not isinstance(executor, Mapping):
        return "unknown"
    executor_config = cast("Mapping[str, Any]", executor)
    shadow_mode = executor_config.get("shadow_mode")
    if shadow_mode is True:
        return "shadow"
    if shadow_mode is False:
        return "live"
    return "unknown"


def build_installation_stats_payload(
    config: Mapping[str, Any], installation_id: str, *, version: str | None = None
) -> dict[str, str]:
    """Build only the seven explicitly allowed heartbeat fields."""
    if version is None:
        from backend.core.version import get_version

        version = get_version()
    return {
        "installation_id": installation_id,
        "version": version,
        "release_channel": classify_release_channel(),
        "installation_type": classify_installation_type(),
        "architecture": normalize_architecture(),
        "inverter_profile": classify_inverter_profile(config),
        "execution_mode": classify_execution_mode(config),
    }


def is_valid_payload(payload: object) -> bool:
    """Validate the bounded receiver contract without retaining unknown fields."""
    if not isinstance(payload, dict):
        return False
    candidate = cast("dict[str, object]", payload)
    if frozenset(candidate) != PAYLOAD_FIELDS:
        return False
    if any(not isinstance(value, str) for value in candidate.values()):
        return False
    fields = cast("dict[str, str]", candidate)
    version = fields["version"]
    if not version or len(version) > 128:
        return False
    try:
        identifier = uuid.UUID(fields["installation_id"])
    except (ValueError, AttributeError, TypeError):
        return False
    return (
        identifier.version == 4
        and identifier.variant == uuid.RFC_4122
        and fields["release_channel"] in RELEASE_CHANNELS
        and fields["installation_type"] in INSTALLATION_TYPES
        and fields["architecture"] in ARCHITECTURES
        and fields["inverter_profile"] in BUILT_IN_INVERTER_PROFILES | {"custom", "unknown"}
        and fields["execution_mode"] in EXECUTION_MODES
    )
