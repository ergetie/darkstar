"""Shared live EV state reader (ev-live-state).

One place decides what a charger's live "SoC" and "plugged in" mean, so the
manual-charge start API and the executor's manual-charge end check cannot
drift apart. Unlike ``resolve_plug_state`` (dashboard display), an
unreachable plug is reported as ``unknown`` — never as the last known reading.

Every valid SoC reading is also remembered as the charger's last-known SoC
(with its reading time). ``resolve_soc`` turns a live reading plus that
memory into a resolved SoC with a status (ev-soc-staleness): ``live``,
``carried`` (a recent valid reading within ``soc_stale_after_minutes``) or
``stale`` (none).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from backend.core.ev_plug import is_ev_plugged_in, is_unreachable_state, remember_plug_state

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

EVPlugState = Literal["plugged", "unplugged", "unknown"]
EVSocStatus = Literal["live", "carried", "stale"]

DEFAULT_SOC_STALE_AFTER_MINUTES = 15.0

# Last valid SoC reading per charger id: (soc_percent, reading time UTC).
# Shared by the planner's REST reads, the EV API and the executor.
_soc_lock = threading.Lock()
_last_known_soc: dict[str, tuple[float, datetime]] = {}
# Chargers currently in a stale-SoC episode (plugged, SoC sensor configured,
# resolved status ``stale``) -> age of the last valid reading in minutes
# (None when there never was one in this process).
_stale_episodes: dict[str, float | None] = {}
# Chargers whose stale-SoC episode was ended by a valid reading and whose
# recovery has not yet been consumed (triggers one replan per episode).
_soc_recoveries: set[str] = set()


@dataclass(frozen=True)
class EVLiveState:
    soc_percent: float | None
    plug: EVPlugState


@dataclass(frozen=True)
class ResolvedSoc:
    """A charger's SoC as consumers should use it (ev-soc-staleness)."""

    soc_percent: float | None
    status: EVSocStatus
    age_minutes: float | None


def soc_stale_after_minutes(charger_cfg: dict[str, Any] | None) -> float:
    """The charger's carry window (``ev_chargers[].soc_stale_after_minutes``, default 15)."""
    raw = (charger_cfg or {}).get("soc_stale_after_minutes")
    try:
        value = float(raw) if raw is not None else DEFAULT_SOC_STALE_AFTER_MINUTES
    except (TypeError, ValueError):
        return DEFAULT_SOC_STALE_AFTER_MINUTES
    return value if value >= 0 else DEFAULT_SOC_STALE_AFTER_MINUTES


def remember_soc(charger_id: str, soc_percent: float, at: datetime | None = None) -> None:
    """Record a valid SoC reading as the charger's last-known SoC.

    A valid reading also ends the charger's stale-SoC episode, if any, and
    records the recovery for ``consume_soc_recoveries``.
    """
    with _soc_lock:
        _last_known_soc[charger_id] = (float(soc_percent), at or datetime.now(UTC))
        if charger_id in _stale_episodes:
            del _stale_episodes[charger_id]
            _soc_recoveries.add(charger_id)


def last_known_soc(charger_id: str) -> tuple[float, datetime] | None:
    """The last valid SoC reading and its time, or None if none was seen."""
    with _soc_lock:
        return _last_known_soc.get(charger_id)


def resolve_soc(
    charger_id: str,
    live_soc: float | None,
    stale_after_minutes: float = DEFAULT_SOC_STALE_AFTER_MINUTES,
    now: datetime | None = None,
) -> ResolvedSoc:
    """Resolve a charger's SoC from its live reading and last-known memory.

    A valid live reading is remembered and returned as ``live``. Without one,
    the last-known reading is ``carried`` while it is at most
    ``stale_after_minutes`` old; otherwise the SoC is ``stale`` (None).
    SoC reads are wall-clock, so ``now`` defaults to the real time.
    """
    current = now or datetime.now(UTC)
    if live_soc is not None:
        remember_soc(charger_id, live_soc, current)
        return ResolvedSoc(float(live_soc), "live", 0.0)
    last = last_known_soc(charger_id)
    if last is None:
        return ResolvedSoc(None, "stale", None)
    value, read_at = last
    age = max(0.0, (current - read_at).total_seconds() / 60.0)
    if age <= stale_after_minutes:
        return ResolvedSoc(value, "carried", age)
    return ResolvedSoc(None, "stale", age)


def update_stale_soc_episode(charger_id: str, resolved: ResolvedSoc | None) -> None:
    """Track stale-SoC episodes for the notification (one per episode).

    Pass None (or a non-stale result) to end the charger's episode, e.g. when
    it is unplugged or has a valid reading again.
    """
    with _soc_lock:
        if resolved is not None and resolved.status == "stale":
            _stale_episodes[charger_id] = resolved.age_minutes
        else:
            _stale_episodes.pop(charger_id, None)


def stale_soc_episodes() -> dict[str, float | None]:
    """Chargers currently in a stale-SoC episode -> last reading age (minutes)."""
    with _soc_lock:
        return dict(_stale_episodes)


def consume_soc_recoveries() -> set[str]:
    """Chargers whose stale-SoC episode ended with a valid reading since the last call.

    Each recovery is returned exactly once (one replan per episode).
    """
    with _soc_lock:
        recovered = set(_soc_recoveries)
        _soc_recoveries.clear()
        return recovered


def discard_soc_recovery(charger_id: str) -> None:
    """Drop a pending recovery that a planner run has already planned from."""
    with _soc_lock:
        _soc_recoveries.discard(charger_id)


def reset_soc_memory() -> None:
    """Forget all last-known SoC readings, stale episodes and recoveries (test isolation)."""
    with _soc_lock:
        _last_known_soc.clear()
        _stale_episodes.clear()
        _soc_recoveries.clear()


def _interpret_soc(raw_soc: object) -> float | None:
    if raw_soc is None or is_unreachable_state(raw_soc):
        return None
    try:
        return float(str(raw_soc).strip())
    except (TypeError, ValueError):
        return None


def interpret_ev_live_state(
    charger_id: str,
    raw_soc: object,
    raw_plug: object,
    *,
    has_soc_sensor: bool,
    has_plug_sensor: bool,
    plugged_in_states: object = None,
) -> EVLiveState:
    """Interpret raw HA states into an ``EVLiveState`` (no I/O).

    A valid plug reading is recorded as the charger's last known plug state,
    which the dashboard shows while the charger is unreachable.
    """
    soc = _interpret_soc(raw_soc) if has_soc_sensor else None
    if soc is not None:
        remember_soc(charger_id, soc)

    plug: EVPlugState
    if not has_plug_sensor:
        # No plug sensor → assumed plugged in (same as the planner).
        plug = "plugged"
    elif raw_plug is None or is_unreachable_state(raw_plug):
        plug = "unknown"
    else:
        plugged_in = is_ev_plugged_in(raw_plug, plugged_in_states)
        remember_plug_state(charger_id, plugged_in)
        plug = "plugged" if plugged_in else "unplugged"

    return EVLiveState(soc_percent=soc, plug=plug)


async def read_ev_live_state(
    charger_id: str,
    get_state: Callable[[str], Awaitable[str | None]],
    *,
    soc_sensor: str | None,
    plug_sensor: str | None,
    plugged_in_states: object = None,
) -> EVLiveState:
    """Read and interpret a charger's live SoC and plug state.

    ``get_state`` returns an entity's raw HA state string. A read that raises
    is logged and treated as a missing value.
    """

    async def _read(entity_id: str | None, what: str) -> str | None:
        if not entity_id:
            return None
        try:
            return await get_state(entity_id)
        except Exception as exc:
            logger.warning("EV %s: %s read failed (%s): %s", charger_id, what, entity_id, exc)
            return None

    raw_soc = await _read(soc_sensor, "SoC")
    raw_plug = await _read(plug_sensor, "plug")
    return interpret_ev_live_state(
        charger_id,
        raw_soc,
        raw_plug,
        has_soc_sensor=bool(soc_sensor),
        has_plug_sensor=bool(plug_sensor),
        plugged_in_states=plugged_in_states,
    )
