"""Shared EV plug-state interpretation.

Home Assistant integrations expose connected EVs with different state names.
Keep the normalization here so REST reads, WebSocket updates, and API
aggregates cannot drift apart.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger("darkstar.core.ev_plug")

DEFAULT_EV_PLUGGED_IN_STATES = "on,true,1,connected"

# HA states meaning the charger integration lost contact with the device. A
# charger in one of these states is *unreachable*, not unplugged
# (ev-missed-goal-recovery).
EV_UNREACHABLE_STATES = frozenset({"unavailable", "unknown"})

# A not-plugged reading only ends a plug session once it has persisted this
# long; a shorter one is a flicker (charger glitch, brief unplug) and the
# session continues (ev-missed-goal-recovery).
EV_UNPLUG_DEBOUNCE_MINUTES = 10
_UNPLUG_DEBOUNCE = timedelta(minutes=EV_UNPLUG_DEBOUNCE_MINUTES)

# Key under a charger's entry in the EV state file holding its plug session
# (``{"start": iso, "first_unplugged_at": iso | None}``). Shares the entry with
# the goal and manual charge; it is not a goal.
EV_PLUG_SESSION_STATE_KEY = "plug_session"

# Last valid plug reading per charger id, shared by the WebSocket handler and
# the planner's REST reads so an unreachable charger keeps its last known state.
_last_known_lock = threading.Lock()
_last_known_plugged: dict[str, bool] = {}
# Start of the current continuous plug session per charger (missed-goal grace
# continuity). Recorded on an observed unplugged -> plugged transition or
# restored from the EV state file after a restart; a charger first seen plugged
# with nothing restorable has no entry, i.e. unknown history, never "just
# replugged".
_plug_session_start: dict[str, datetime] = {}
# When the current not-plugged streak began, while a session is still pending.
_first_unplugged_at: dict[str, datetime] = {}


def _parse_ts(raw: object) -> datetime | None:
    """Parse a persisted ISO timestamp (naive -> UTC); None when absent/invalid."""
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _load_persisted_session(charger_id: str) -> tuple[datetime | None, datetime | None]:
    """Saved ``(start, first_unplugged_at)`` for a charger; ``(None, None)`` if unusable."""
    from backend.core.ev_state import read_ev_state

    try:
        entry = read_ev_state().get(charger_id)
    except Exception as exc:
        logger.warning("EV %s: could not read saved plug session: %s", charger_id, exc)
        return (None, None)
    raw = entry.get(EV_PLUG_SESSION_STATE_KEY) if isinstance(entry, dict) else None
    if not isinstance(raw, dict):
        return (None, None)
    raw_session = cast("dict[str, Any]", raw)
    start = _parse_ts(raw_session.get("start"))
    if start is None:
        return (None, None)
    return (start, _parse_ts(raw_session.get("first_unplugged_at")))


def _persist_session(
    charger_id: str, start: datetime | None, first_unplugged: datetime | None
) -> None:
    """Write (or remove, when ``start`` is None) a charger's plug session; goal untouched."""
    from backend.core.ev_state import update_ev_state

    def _mutate(state: dict[str, dict[str, Any]]) -> None:
        entry = state.get(charger_id)
        if start is None:
            if not isinstance(entry, dict) or EV_PLUG_SESSION_STATE_KEY not in entry:
                return
            entry.pop(EV_PLUG_SESSION_STATE_KEY, None)
            if not entry:
                state.pop(charger_id, None)
            return
        if not isinstance(entry, dict):
            entry = {}
        entry[EV_PLUG_SESSION_STATE_KEY] = {
            "start": start.isoformat(),
            "first_unplugged_at": first_unplugged.isoformat() if first_unplugged else None,
        }
        state[charger_id] = entry

    try:
        update_ev_state(_mutate)
    except Exception as exc:
        logger.warning("EV %s: could not save plug session: %s", charger_id, exc)


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


def remember_plug_state(charger_id: str, plugged_in: bool, now: datetime | None = None) -> None:
    """Record the last valid plug reading for a charger and track its plug session.

    An observed unplugged -> plugged transition starts a session at ``now``
    (default: current UTC time); plugged -> plugged keeps it. A not-plugged
    reading only ends the session once it has persisted
    ``EV_UNPLUG_DEBOUNCE_MINUTES``; a plugged reading inside that window keeps
    the original start. A first-ever plugged reading restores the session saved
    in the EV state file (if the car was not gone longer than the debounce),
    else leaves the start unknown. The state file is written only when the
    session changes. Unreachable readings never reach this function.
    """
    now = now or datetime.now(UTC)
    saved: tuple[datetime | None, datetime | None] | None = None
    drop_stale = False
    with _last_known_lock:
        first_reading = charger_id not in _last_known_plugged
    if first_reading:
        saved = _load_persisted_session(charger_id)

    with _last_known_lock:
        if charger_id not in _last_known_plugged and saved is not None:
            saved_start, saved_unplugged = saved
            if plugged_in:
                restorable = saved_unplugged is None or now - saved_unplugged < _UNPLUG_DEBOUNCE
            else:
                # An unplugged first reading can only continue a debounce that
                # was already running; otherwise how long the car was gone is
                # unknown. (An expired one is ended by the normal rule below.)
                restorable = saved_unplugged is not None
            if saved_start is not None and restorable:
                _plug_session_start[charger_id] = saved_start
                if saved_unplugged is not None:
                    _first_unplugged_at[charger_id] = saved_unplugged
            drop_stale = saved_start is not None and not restorable

        previous = _last_known_plugged.get(charger_id)
        before = (_plug_session_start.get(charger_id), _first_unplugged_at.get(charger_id))
        _last_known_plugged[charger_id] = plugged_in
        start, unplugged_since = before

        if plugged_in:
            if unplugged_since is not None and now - unplugged_since >= _UNPLUG_DEBOUNCE:
                start = now  # the session had ended: this is a replug
            elif start is None and previous is False:
                start = now
            unplugged_since = None
        elif start is not None:
            if unplugged_since is None:
                unplugged_since = now
            elif now - unplugged_since >= _UNPLUG_DEBOUNCE:
                start, unplugged_since = None, None

        if start is None:
            _plug_session_start.pop(charger_id, None)
        else:
            _plug_session_start[charger_id] = start
        if unplugged_since is None:
            _first_unplugged_at.pop(charger_id, None)
        else:
            _first_unplugged_at[charger_id] = unplugged_since
        changed = (start, unplugged_since) != before

    if changed:
        _persist_session(charger_id, start, unplugged_since)
    elif drop_stale:
        _persist_session(charger_id, None, None)


def plug_session_start(charger_id: str) -> datetime | None:
    """Start of the charger's current plug session, or None when unknown."""
    with _last_known_lock:
        return _plug_session_start.get(charger_id)


def reset_plug_memory() -> None:
    """Forget all plug readings and sessions (test isolation)."""
    with _last_known_lock:
        _last_known_plugged.clear()
        _plug_session_start.clear()
        _first_unplugged_at.clear()


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
