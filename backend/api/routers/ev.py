"""Read-only EV state API (price-forecasting-module-4 section 5.1-5.3).

``GET /api/ev/chargers`` merges per-charger transient goal/progress state
(written by the planner pipeline to ``data/ev_multi_day_state.json``) with
live Home Assistant sensor data fetched on request. Used by Module 5's UI.

No ``charge_priority`` field is returned — it does not exist in this change.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, date, datetime
from typing import Any

import pytz
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from backend.core.ev_goal import resolve_next_ready_by
from backend.core.ev_state import read_ev_state, update_ev_state
from backend.core.ha_client import get_ha_bool, get_ha_sensor_float, get_ha_sensor_kw_normalized
from backend.core.secrets import load_yaml

logger = logging.getLogger("darkstar.api.ev")

router = APIRouter(prefix="/api/ev", tags=["ev"])


class EVChargerScheduleBody(BaseModel):
    target_soc_percent: int | None = Field(default=None)
    ready_by: str | None = Field(default=None)
    repeat: str | None = Field(default=None)
    ready_by_date: str | None = Field(default=None)
    n_days: int | None = Field(default=None)
    keep_on_after_target: bool | None = Field(default=None)


def _get_ha_client() -> Any:
    """Return the backend-owned HA action client for the current event loop.

    Never the executor's own ``HAClient`` instance — that one belongs to the
    executor's (possibly different) loop, and closing/using a session across
    loops raises "Future attached to a different loop".
    """
    from backend.core.ha_client import get_ha_action_client

    try:
        return get_ha_action_client()
    except Exception as exc:
        logger.warning("Could not obtain HA action client: %s", exc)
        return None


async def sync_goal_to_ha(
    charger_id: str,
    target_soc: int | None,
    ready_by_dt: datetime | None,
    ha_target_soc_entity: str | None,
    ha_ready_by_entity: str | None,
):
    ha = _get_ha_client()
    if not ha:
        logger.warning("Could not sync goal to HA: HAClient not available")
        return

    # Record the write time for debounce (prevent echoes loop)
    from backend.core.ev_state import last_darkstar_write

    last_darkstar_write[charger_id] = time.time()

    # Sync target SoC
    if ha_target_soc_entity and target_soc is not None:
        try:
            logger.info("Syncing target SoC %d to HA entity %s", target_soc, ha_target_soc_entity)
            await ha.set_input_number(ha_target_soc_entity, float(target_soc))
        except Exception as e:
            logger.warning("Failed to sync target SoC to HA entity %s: %s", ha_target_soc_entity, e)

    # Sync ready-by
    if ha_ready_by_entity and ready_by_dt is not None:
        try:
            logger.info("Syncing ready-by %s to HA entity %s", ready_by_dt, ha_ready_by_entity)
            await ha.set_input_datetime(ha_ready_by_entity, ready_by_dt)
        except Exception as e:
            logger.warning("Failed to sync ready-by to HA entity %s: %s", ha_ready_by_entity, e)


@router.post(
    "/chargers/{id}/schedule",
    summary="Set EV Charger Schedule",
    description="Set or clear the target SoC, ready-by time, and repeat settings for a charger.",
)
async def set_ev_charger_schedule(
    id: str,
    body: EVChargerScheduleBody,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    # 1. Load config and find charger
    config = load_yaml("config.yaml")
    ev_chargers_cfg: list[dict[str, Any]] = config.get("ev_chargers", []) or []
    charger_cfg = None
    for ev in ev_chargers_cfg:
        if str(ev.get("id")) == id and ev.get("enabled", True):
            charger_cfg = ev
            break

    if not charger_cfg:
        raise HTTPException(status_code=404, detail="Charger not found")

    # 2. Validation
    if body.target_soc_percent is not None:
        if not (0 <= body.target_soc_percent <= 100):
            raise HTTPException(
                status_code=422, detail="target_soc_percent must be between 0 and 100"
            )

        if not body.ready_by:
            raise HTTPException(
                status_code=422, detail="ready_by is required when target_soc_percent is set"
            )

        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", body.ready_by):
            raise HTTPException(status_code=422, detail="ready_by must be in HH:MM format")

        if not body.repeat:
            raise HTTPException(
                status_code=422, detail="repeat is required when target_soc_percent is set"
            )

        allowed_repeats = {"daily", "weekdays", "weekends", "every_n_days", "none"}
        if body.repeat not in allowed_repeats:
            raise HTTPException(status_code=422, detail="Invalid repeat mode")

        if body.repeat == "none" and not body.ready_by_date:
            raise HTTPException(
                status_code=422, detail="ready_by_date is required when repeat is none"
            )

        if body.repeat == "none" and body.ready_by_date:
            try:
                date.fromisoformat(body.ready_by_date)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422, detail="ready_by_date must be a valid YYYY-MM-DD date"
                ) from exc

            timezone_name = config.get("timezone", "Europe/Stockholm")
            tz = pytz.timezone(timezone_name)
            probe_goal = {
                "ready_by": body.ready_by,
                "repeat": body.repeat,
                "ready_by_date": body.ready_by_date,
            }
            if resolve_next_ready_by(probe_goal, datetime.now(tz), tz) is None:
                raise HTTPException(
                    status_code=422,
                    detail="ready_by_date/ready_by must resolve to a future deadline",
                )

    if body.n_days is not None and body.n_days < 1:
        raise HTTPException(status_code=422, detail="n_days must be an integer >= 1")

    # 3. Read and update state file (locked read-modify-write)
    now = datetime.now(UTC)
    new_charger_state: dict[str, Any] = {}

    def _mutate(state: dict[str, dict[str, Any]]) -> None:
        nonlocal new_charger_state
        if body.target_soc_percent is None:
            # Clear the goal
            state.pop(id, None)
            new_charger_state = {}
            return
        charger_state = state.get(id, {})
        charger_state.update(
            {
                "target_soc_percent": body.target_soc_percent,
                "ready_by": body.ready_by,
                "repeat": body.repeat,
                "ready_by_date": body.ready_by_date,
                "n_days": body.n_days,
                "keep_on_after_target": body.keep_on_after_target
                if body.keep_on_after_target is not None
                else False,
                "source": "api",
                "last_updated": now.isoformat(),
            }
        )
        state[id] = charger_state
        new_charger_state = charger_state

    update_ev_state(_mutate)
    charger_state = new_charger_state

    # 4. Trigger fire-and-forget sync to HA in background if entities configured
    ha_ready_by_entity = charger_cfg.get("ha_ready_by_entity")
    ha_target_soc_entity = charger_cfg.get("ha_target_soc_entity")

    if (ha_ready_by_entity or ha_target_soc_entity) and body.target_soc_percent is not None:
        timezone_name = config.get("timezone", "Europe/Stockholm")
        tz = pytz.timezone(timezone_name)
        ready_by_dt = resolve_next_ready_by(charger_state, datetime.now(tz), tz)
        background_tasks.add_task(
            sync_goal_to_ha,
            id,
            body.target_soc_percent,
            ready_by_dt,
            ha_target_soc_entity,
            ha_ready_by_entity,
        )

    # 5. Return updated charger state
    all_chargers = await get_ev_chargers()
    for c in all_chargers:
        if c["id"] == id:
            return c

    raise HTTPException(status_code=404, detail="Charger not found after update")


def _load_ev_state() -> dict[str, dict[str, Any]]:
    """Read the transient EV state file. Returns ``{}`` if missing/unreadable."""
    return read_ev_state()


def _parse_iso_deadline(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _compute_status(
    plugged_in: bool,
    deadline: datetime | None,
    required_kwh: float | None,
    max_power_kw: float,
    now: datetime,
) -> str:
    """Classify a charger: on_track | behind | complete | idle."""
    if not plugged_in or deadline is None or required_kwh is None:
        return "idle"
    if required_kwh <= 0.0:
        return "complete"
    seconds_left = (deadline - now).total_seconds()
    if seconds_left <= 0.0:
        return "behind"
    deliverable = max_power_kw * (seconds_left / 3600.0)
    return "on_track" if deliverable + 1e-6 >= required_kwh else "behind"


@router.get(
    "/chargers",
    summary="Get EV Charger Status",
    description=(
        "Per-charger live HA sensor data merged with goal and progress from the "
        "last pipeline run. ``status ∈ {on_track, behind, complete, idle}``."
    ),
)
async def get_ev_chargers() -> list[dict[str, Any]]:
    """Return all configured EV chargers with live sensors, goal, progress, status."""
    config = load_yaml("config.yaml")
    ev_chargers_cfg: list[dict[str, Any]] = config.get("ev_chargers", []) or []
    state_by_id = _load_ev_state()
    now = datetime.now(UTC)

    async def _safe_float(entity_id: str) -> float | None:
        if not entity_id:
            return None
        try:
            return await get_ha_sensor_float(entity_id)
        except Exception as exc:
            logger.warning("Failed to read HA sensor %s: %s", entity_id, exc)
            return None

    async def _safe_kw(entity_id: str) -> float | None:
        if not entity_id:
            return None
        try:
            return await get_ha_sensor_kw_normalized(entity_id)
        except Exception as exc:
            logger.warning("Failed to read HA sensor %s: %s", entity_id, exc)
            return None

    async def _safe_bool(entity_id: str) -> bool | None:
        if not entity_id:
            return None
        try:
            return await get_ha_bool(entity_id)
        except Exception as exc:
            logger.warning("Failed to read HA sensor %s: %s", entity_id, exc)
            return None

    out: list[dict[str, Any]] = []
    for ev in ev_chargers_cfg:
        if not ev.get("enabled", True):
            continue
        charger_id = str(ev.get("id", ""))

        power_kw = await _safe_kw(str(ev.get("sensor", "")))
        soc_percent = await _safe_float(str(ev.get("soc_sensor", "")))
        plugged_in = await _safe_bool(str(ev.get("plug_sensor", "")))

        persisted = state_by_id.get(charger_id, {})

        max_power_kw = float(ev.get("max_power_kw") or 7.4)

        externally_controlled = False
        if ev.get("type", "current") == "binary":
            externally_controlled = not bool(ev.get("switch_entity"))
        else:
            externally_controlled = not bool(ev.get("current_entity"))

        if not persisted:
            # No goal set for this charger → idle with null goal-progress; live sensors only.
            out.append(
                {
                    "id": charger_id,
                    "name": ev.get("name", charger_id),
                    "plugged_in": plugged_in,
                    "soc_percent": round(soc_percent, 1) if soc_percent is not None else None,
                    "power_kw": round(power_kw, 3) if power_kw is not None else None,
                    "target_soc_percent": None,
                    "ready_by": None,
                    "repeat": None,
                    "deadline": None,
                    "required_kwh": None,
                    "delivered_kwh": None,
                    "remaining_kwh": None,
                    "daily_quota_kwh": None,
                    "quota_schedule": None,
                    "keep_on_after_target": bool(ev.get("keep_on_after_target", False)),
                    "ha_ready_by_entity": ev.get("ha_ready_by_entity"),
                    "ha_target_soc_entity": ev.get("ha_target_soc_entity"),
                    "type": ev.get("type", "current"),
                    "n_days": None,
                    "ready_by_date": None,
                    "status": "idle",
                    "source": None,
                    "externally_controlled": externally_controlled,
                    "last_updated": None,
                    "last_planned_at": None,
                }
            )
            continue

        deadline = _parse_iso_deadline(persisted.get("deadline"))
        required_kwh = persisted.get("required_kwh")
        if isinstance(required_kwh, str):
            try:
                required_kwh = float(required_kwh)
            except ValueError:
                required_kwh = None

        # Re-derive live status: if the live SoC already meets the target, mark complete.
        live_soc = soc_percent if soc_percent is not None else persisted.get("current_soc_percent")
        target_soc_cfg = persisted.get("target_soc_percent")
        if (
            live_soc is not None
            and target_soc_cfg is not None
            and float(live_soc) >= float(target_soc_cfg) - 1e-6
        ):
            status = "complete"
        else:
            status = _compute_status(
                plugged_in if plugged_in is not None else False,
                deadline,
                required_kwh if required_kwh is not None else None,
                max_power_kw,
                now,
            )

        out.append(
            {
                "id": charger_id,
                "name": ev.get("name", charger_id),
                "plugged_in": plugged_in,
                "soc_percent": round(soc_percent, 1) if soc_percent is not None else None,
                "power_kw": round(power_kw, 3) if power_kw is not None else None,
                "target_soc_percent": persisted.get("target_soc_percent"),
                "ready_by": persisted.get("ready_by"),
                "repeat": persisted.get("repeat"),
                "deadline": persisted.get("deadline"),
                "required_kwh": persisted.get("required_kwh"),
                "delivered_kwh": persisted.get("delivered_kwh"),
                "remaining_kwh": persisted.get("remaining_kwh"),
                "daily_quota_kwh": persisted.get("daily_quota_kwh"),
                "quota_schedule": persisted.get("quota_schedule"),
                "keep_on_after_target": bool(persisted.get("keep_on_after_target", False)),
                "ha_ready_by_entity": ev.get("ha_ready_by_entity"),
                "ha_target_soc_entity": ev.get("ha_target_soc_entity"),
                "type": ev.get("type", "current"),
                "n_days": persisted.get("n_days"),
                "ready_by_date": persisted.get("ready_by_date"),
                "status": status,
                "source": persisted.get("source"),
                "externally_controlled": externally_controlled,
                "last_updated": persisted.get("last_updated"),
                "last_planned_at": persisted.get("last_planned_at"),
            }
        )

    return out
