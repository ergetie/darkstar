"""Receiver-local payload contract, independent of the Darkstar runtime."""

from __future__ import annotations

import uuid
from typing import cast

LEGACY_PAYLOAD_FIELDS = frozenset(
    {
        "installation_id",
        "version",
        "release_channel",
        "installation_type",
        "architecture",
        "inverter_profile",
    }
)
PAYLOAD_FIELDS = LEGACY_PAYLOAD_FIELDS | {"execution_mode"}
BUILT_IN_INVERTER_PROFILES = frozenset({"deye", "fronius", "generic", "sungrow"})
RELEASE_CHANNELS = frozenset({"stable", "dev", "unknown"})
INSTALLATION_TYPES = frozenset({"ha_addon", "docker", "unknown"})
ARCHITECTURES = frozenset({"amd64", "aarch64", "unknown"})
INVERTER_PROFILES = BUILT_IN_INVERTER_PROFILES | {"custom", "unknown"}
EXECUTION_MODES = frozenset({"shadow", "live", "unknown"})


def validate_payload(payload: object) -> dict[str, str] | None:
    """Return the normalized allowed payload, or None when it is invalid."""
    if not isinstance(payload, dict):
        return None
    candidate = cast("dict[str, object]", payload)
    supplied_fields = frozenset(candidate)
    legacy_payload = supplied_fields == LEGACY_PAYLOAD_FIELDS
    if not legacy_payload and supplied_fields != PAYLOAD_FIELDS:
        return None
    if any(not isinstance(value, str) for value in candidate.values()):
        return None
    fields = cast("dict[str, str]", candidate)
    version = fields["version"]
    if not version or len(version) > 128:
        return None
    try:
        identifier = uuid.UUID(fields["installation_id"])
    except (ValueError, AttributeError, TypeError):
        return None
    if identifier.version != 4 or identifier.variant != uuid.RFC_4122:
        return None
    if fields["release_channel"] not in RELEASE_CHANNELS:
        return None
    if fields["installation_type"] not in INSTALLATION_TYPES:
        return None
    if fields["architecture"] not in ARCHITECTURES:
        return None
    if fields["inverter_profile"] not in INVERTER_PROFILES:
        return None
    if not legacy_payload and fields["execution_mode"] not in EXECUTION_MODES:
        return None
    normalized = {
        **{key: fields[key] for key in LEGACY_PAYLOAD_FIELDS},
        "execution_mode": fields.get("execution_mode", "unknown"),
    }
    normalized["installation_id"] = str(identifier)
    return normalized
