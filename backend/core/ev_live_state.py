"""Shared live EV state reader (ev-live-state).

One place decides what a charger's live "SoC" and "plugged in" mean, so the
manual-charge start API and the executor's manual-charge end check cannot
drift apart. Unlike ``resolve_plug_state`` (dashboard display), an
unreachable plug is reported as ``unknown`` — never as the last known reading.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from backend.core.ev_plug import is_ev_plugged_in, is_unreachable_state, remember_plug_state

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

EVPlugState = Literal["plugged", "unplugged", "unknown"]


@dataclass(frozen=True)
class EVLiveState:
    soc_percent: float | None
    plug: EVPlugState


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
