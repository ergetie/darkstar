"""Deye Time of Use program-time verification.

With all six program times at 00:00 the inverter runs program 6 all day, so
Darkstar can write program 6 SoC directly. The six time entities are derived
from the configured ``soc_target`` entity (``soc`` -> ``time`` naming).
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any, Literal, cast

PROGRAM_SOC_RE = re.compile(
    r"^(number|input_number)\.(.*?)(prog(?:ram)?[ _]?)([1-6])([ _].*)$", re.IGNORECASE
)
_LAST_SOC_RE = re.compile(r"soc(?!.*soc)", re.IGNORECASE)
MIDNIGHT_STATES = frozenset({"00:00", "00:00:00"})
UNVERIFIABLE_STATES = frozenset({"unavailable", "unknown", ""})
PROGRAM_TIMES_PROFILE = "deye"

VerifyStatus = Literal["ok", "mismatch", "unverifiable"]
StateFetcher = Callable[[str], Awaitable[dict[str, Any] | None]]


def derive_program_time_entities(soc_entity: str | None) -> list[str] | None:
    """Derive program 1-6 time entity IDs from a program SoC entity.

    Returns None when the entity has no program number or no ``soc`` token
    after it (e.g. the legacy ``input_number.master_soc_target`` helper).
    """
    if not soc_entity:
        return None
    match = PROGRAM_SOC_RE.match(soc_entity.strip())
    if not match:
        return None
    _domain, prefix, program, _number, suffix = match.groups()
    if not _LAST_SOC_RE.search(suffix):
        return None
    time_suffix = _LAST_SOC_RE.sub(lambda m: "TIME" if m.group().isupper() else "time", suffix)
    return [f"time.{prefix}{program}{n}{time_suffix}" for n in range(1, 7)]


async def verify_program_times(soc_entity: str | None, fetch_state: StateFetcher) -> dict[str, Any]:
    """Check that all six derived program times are 00:00.

    Returns ``{"status": ok|mismatch|unverifiable, "entities": [...],
    "mismatches": [{"entity_id", "value"}]}``. Any entity that cannot be read
    (missing, unavailable, unknown) makes the result ``unverifiable`` unless a
    readable entity already shows a mismatch.
    """
    entities = derive_program_time_entities(soc_entity)
    if entities is None:
        return {"status": "unverifiable", "entities": [], "mismatches": []}
    states = await asyncio.gather(*(fetch_state(e) for e in entities), return_exceptions=True)
    mismatches: list[dict[str, str]] = []
    unreadable = False
    for entity_id, state in zip(entities, states, strict=True):
        value = state.get("state") if isinstance(state, dict) else None
        if not isinstance(value, str) or value.strip().lower() in UNVERIFIABLE_STATES:
            unreadable = True
        elif value.strip() not in MIDNIGHT_STATES:
            mismatches.append({"entity_id": entity_id, "value": value.strip()})
    status: VerifyStatus = "mismatch" if mismatches else "unverifiable" if unreadable else "ok"
    return {"status": status, "entities": entities, "mismatches": mismatches}


def configured_soc_target(config: dict[str, Any]) -> str | None:
    """Return the configured soc_target entity (custom override wins)."""
    executor = cast("dict[str, Any]", config.get("executor") or {})
    inverter = cast("dict[str, Any]", executor.get("inverter") or {})
    custom = cast("dict[str, Any]", inverter.get("custom_entities") or {})
    value: Any = custom.get("soc_target") or inverter.get("soc_target")
    return value if isinstance(value, str) and value else None
