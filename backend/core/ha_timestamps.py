"""Freshness timestamps for live Home Assistant sensor readings.

HA exposes three timestamps per state:

- ``last_changed``: the value changed
- ``last_updated``: the value or attributes changed
- ``last_reported`` (HA >= 2024.3): any report, even an identical value

The age of a *live* reading must be judged from ``last_reported`` so a healthy
sensor that keeps reporting a steady value is not mistaken for a silent one.
History-series consumers (ML features, history import, energy recorder
scaling) intentionally keep using value-change time and must not use this.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

_FRESHNESS_KEYS = ("last_reported", "last_updated", "last_changed")


def _parse(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def reading_timestamp(state: Mapping[str, Any] | None) -> datetime | None:
    """Return when HA last received a report for this state, tz-aware.

    Tries ``last_reported`` → ``last_updated`` → ``last_changed``, skipping
    missing or unparseable values. Returns ``None`` if none is usable.
    """
    if not state:
        return None
    for key in _FRESHNESS_KEYS:
        parsed = _parse(state.get(key))
        if parsed is not None:
            return parsed
    return None
