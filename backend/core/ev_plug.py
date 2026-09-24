"""Shared EV plug-state interpretation.

Home Assistant integrations expose connected EVs with different state names.
Keep the normalization here so REST reads, WebSocket updates, and API
aggregates cannot drift apart.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterable

DEFAULT_EV_PLUGGED_IN_STATES = "on,true,1,connected"

# HA states meaning the charger integration lost contact with the device. A
# charger in one of these states is *unreachable*, not unplugged
# (ev-missed-goal-recovery).
EV_UNREACHABLE_STATES = frozenset({"unavailable", "unknown"})

# Last valid plug reading per charger id, shared by the WebSocket handler and
# the planner's REST reads so an unreachable charger keeps its last known state.
_last_known_lock = threading.Lock()
_last_known_plugged: dict[str, bool] = {}


def parse_ev_plugged_in_states(configured_states: object = None) -> frozenset[str]:
    """Return normalized connected-state tokens from a configured CSV value."""
    raw = DEFAULT_EV_PLUGGED_IN_STATES if configured_states is None else configured_states
    if isinstance(raw, str):
        values: Iterable[object] = raw.split(",")
    elif isinstance(raw, (list, tuple, set, frozenset)):
        values = cast("Iterable[object]", raw)
    else:
        values = (raw,)
    return frozenset(str(token).strip().casefold() for token in values if str(token).strip())


def is_ev_plugged_in(raw_state: object, configured_states: object = None) -> bool:
    """Interpret one raw Home Assistant state using a charger's configured CSV."""
    if raw_state is None:
        return False
    return str(raw_state).strip().casefold() in parse_ev_plugged_in_states(configured_states)


def is_unreachable_state(raw_state: object) -> bool:
    """True when a raw HA state means the entity's device is unreachable."""
    if raw_state is None:
        return False
    return str(raw_state).strip().casefold() in EV_UNREACHABLE_STATES


def remember_plug_state(charger_id: str, plugged_in: bool) -> None:
    """Record the last valid plug reading for a charger."""
    with _last_known_lock:
        _last_known_plugged[charger_id] = plugged_in


def last_known_plug_state(charger_id: str) -> bool | None:
    """Return the last valid plug reading for a charger, or None if never seen."""
    with _last_known_lock:
        return _last_known_plugged.get(charger_id)


def resolve_plug_state(
    charger_id: str, raw_state: object, configured_states: object = None
) -> tuple[bool, bool]:
    """Interpret a raw plug-sensor state, keeping the last known state when unreachable.

    Returns ``(plugged_in, unreachable)``. An ``unavailable``/``unknown`` state
    reports the charger's last valid plug reading (``False`` if none was ever
    seen) with ``unreachable=True``. Any other state is interpreted with the
    charger's plug vocabulary and remembered.
    """
    if is_unreachable_state(raw_state):
        last = last_known_plug_state(charger_id)
        return (bool(last), True)
    plugged_in = is_ev_plugged_in(raw_state, configured_states)
    if raw_state is not None:
        remember_plug_state(charger_id, plugged_in)
    return (plugged_in, False)
