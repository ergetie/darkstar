"""Shared EV plug-state interpretation.

Home Assistant integrations expose connected EVs with different state names.
Keep the normalization here so REST reads, WebSocket updates, and API
aggregates cannot drift apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterable

DEFAULT_EV_PLUGGED_IN_STATES = "on,true,1,connected"


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
