"""Read-only EV state API (price-forecasting-module-4 section 5.1-5.3).

``GET /api/ev/chargers`` merges per-charger transient goal/progress state
(written by the planner pipeline to ``data/ev_multi_day_state.json``) with
live Home Assistant sensor data fetched on request. Used by Module 5's UI.

No ``charge_priority`` field is returned — it does not exist in this change.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pytz
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from backend.core.ev_goal import every_n_days_anchor, resolve_next_ready_by
from backend.core.ev_live_state import read_ev_live_state
from backend.core.ev_plug import (
    DEFAULT_EV_PLUGGED_IN_STATES,
    is_unreachable_state,
    resolve_plug_state,
)
from backend.core.ev_power import charger_disabled_reason, charger_max_kw, nominal_voltage_v
from backend.core.ev_state import read_ev_state, update_ev_state
from backend.core.ha_client import (
    get_ha_entity_state,
    get_ha_sensor_float,
    get_ha_sensor_kw_normalized,
)
from backend.core.secrets import load_yaml

logger = logging.getLogger("darkstar.api.ev")

router = APIRouter(prefix="/api/ev", tags=["ev"])

SCHEDULE_PATH = Path("data/schedule.json")
# A goal is "at risk" when the current plan leaves more than this undelivered.
AT_RISK_SHORTFALL_KWH = 0.01
# Diagnostics belong to the active goal only if its required energy matches.
DIAGNOSTICS_REQUIRED_TOLERANCE_KWH = 0.05


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
    goal_tz = pytz.timezone(config.get("timezone", "Europe/Stockholm"))
    new_charger_state: dict[str, Any] = {}

    def _mutate(state: dict[str, dict[str, Any]]) -> None:
        nonlocal new_charger_state
        if body.target_soc_percent is None:
            # Clear the goal, keeping an active manual charge (ev-manual-charge)
            manual_charge = state.get(id, {}).get("manual_charge")
            if manual_charge is not None:
                state[id] = {"manual_charge": manual_charge}
            else:
                state.pop(id, None)
            new_charger_state = {}
            return
        charger_state = state.get(id, {})
        anchor_date = _next_anchor_date(
            charger_state, body, now.astimezone(goal_tz).date(), goal_tz
        )
        charger_state.pop("anchor_date", None)
        if anchor_date is not None:
            charger_state["anchor_date"] = anchor_date
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

    # Fire-and-forget goal-change replan (debounced, coalesced); the response
    # never waits for the planner. The executor applies the plan on its next tick.
    from backend.services.scheduler_service import ReplanReason, request_replan

    request_replan(ReplanReason.GOAL_CHANGE, charger_ids=[id])

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


def _next_anchor_date(
    previous: dict[str, Any],
    body: EVChargerScheduleBody,
    today: date,
    tz: pytz.BaseTzInfo,
) -> str | None:
    """``anchor_date`` for an API goal write (per-device-ev-scheduling / ev-schedule-api).

    Only ``every_n_days`` goals carry an anchor. It re-anchors on today when the
    goal is new to ``every_n_days``, ``n_days`` changed, or no anchor is
    derivable; otherwise the existing anchor (legacy goals: the one derived
    from ``last_updated``, now persisted) is kept so saving other fields never
    moves the cycle.
    """
    if body.repeat != "every_n_days":
        return None
    prev_repeat = str(previous.get("repeat") or "").lower()
    prev_n = previous.get("n_days") or 1
    new_n = body.n_days or 1
    existing = every_n_days_anchor(previous, tz) if prev_repeat == "every_n_days" else None
    if existing is None or prev_n != new_n:
        return today.isoformat()
    return existing.isoformat()


def _plan_pending(charger_id: str, persisted: dict[str, Any]) -> bool:
    """Goal edited after the last plan, or a goal-triggered run queued/running."""
    from backend.services.planner_service import planner_service

    if planner_service.goal_replan_pending(charger_id):
        return True
    goal_edited = _parse_iso_deadline(persisted.get("last_updated"))
    plan_time = _parse_iso_deadline(persisted.get("last_planned_at"))
    if goal_edited is None or plan_time is None or goal_edited <= plan_time:
        return False
    # A failed goal-triggered run is reported (not pending) until the goal changes again.
    failed_at = planner_service.goal_replan_failed_at(charger_id)
    return failed_at is None or failed_at < goal_edited


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
    max_kw: float,
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
    deliverable = max_kw * (seconds_left / 3600.0)
    return "on_track" if deliverable + 1e-6 >= required_kwh else "behind"


def _planned_by_day_view(raw: Any) -> list[dict[str, Any]]:
    """Validated ``planned_by_day`` entries from the state file (malformed ones dropped)."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in cast("list[Any]", raw):
        if not isinstance(item, dict):
            continue
        entry = cast("dict[str, Any]", item)
        day = entry.get("date")
        kwh = entry.get("kwh")
        basis = entry.get("basis")
        if not isinstance(day, str) or not isinstance(kwh, int | float):
            continue
        out.append(
            {
                "date": day,
                "kwh": float(kwh),
                "basis": basis if basis in ("known", "estimated") else "estimated",
            }
        )
    return out


def _load_schedule() -> dict[str, Any]:
    """Read schedule.json. Returns ``{}`` if missing/unreadable."""
    try:
        with SCHEDULE_PATH.open(encoding="utf-8") as f:
            data: Any = json.load(f)
    except (OSError, ValueError):
        return {}
    return cast("dict[str, Any]", data) if isinstance(data, dict) else {}


def _load_schedule_meta(schedule: dict[str, Any] | None = None) -> dict[str, Any]:
    """``meta`` of schedule.json. Returns ``{}`` if missing/unreadable."""
    data = schedule if schedule is not None else _load_schedule()
    meta: Any = data.get("meta")
    return cast("dict[str, Any]", meta) if isinstance(meta, dict) else {}


def _first_planned_starts(schedule: dict[str, Any], now: datetime) -> dict[str, str]:
    """Start (ISO) of each charger's first not-yet-ended slot with planned kW > 0.1."""
    slots: Any = schedule.get("schedule")
    if not isinstance(slots, list):
        return {}
    starts: dict[str, str] = {}
    for item in cast("list[Any]", slots):
        if not isinstance(item, dict):
            continue
        slot = cast("dict[str, Any]", item)
        start = _parse_iso_deadline(slot.get("start_time"))
        end = _parse_iso_deadline(slot.get("end_time_kepler") or slot.get("end_time"))
        if start is None or (end is not None and end <= now):
            continue
        per_charger: Any = slot.get("ev_chargers")
        if not isinstance(per_charger, dict):
            continue
        for charger_id, kw in cast("dict[str, Any]", per_charger).items():
            if isinstance(kw, int | float) and kw > 0.1 and charger_id not in starts:
                starts[str(charger_id)] = start.isoformat()
    return starts


def _active_goal_shortfall(
    diagnostics: dict[str, Any] | None,
    persisted: dict[str, Any],
) -> dict[str, Any] | None:
    """Return the plan's shortfall diagnostics if they belong to the active goal.

    Diagnostics are ignored (stale) when the goal was edited after the plan was
    made, the deadline differs, or the required energy differs by more than
    DIAGNOSTICS_REQUIRED_TOLERANCE_KWH. Only a shortfall above
    AT_RISK_SHORTFALL_KWH is returned.
    """
    if not diagnostics:
        return None
    try:
        shortfall = float(diagnostics.get("shortfall_kwh") or 0.0)
        diag_required = float(diagnostics["required_kwh"])
        goal_required = float(persisted["required_kwh"])
    except (KeyError, TypeError, ValueError):
        return None
    if shortfall <= AT_RISK_SHORTFALL_KWH:
        return None

    diag_deadline = _parse_iso_deadline(diagnostics.get("deadline"))
    goal_deadline = _parse_iso_deadline(persisted.get("deadline"))
    if diag_deadline is None or goal_deadline is None or diag_deadline != goal_deadline:
        return None
    if abs(diag_required - goal_required) > DIAGNOSTICS_REQUIRED_TOLERANCE_KWH:
        return None

    goal_edited = _parse_iso_deadline(persisted.get("last_updated"))
    plan_time = _parse_iso_deadline(persisted.get("last_planned_at"))
    if goal_edited is not None and plan_time is not None and goal_edited > plan_time:
        return None

    return diagnostics


@router.get(
    "/chargers",
    summary="Get EV Charger Status",
    description=(
        "Per-charger live HA sensor data merged with goal and progress from the "
        "last pipeline run. ``status ∈ {on_track, at_risk, behind, complete, idle}``. "
        "``at_risk`` means the current plan will not deliver the goal; see "
        "``shortfall_kwh`` and ``shortfall_reason``."
    ),
)
async def get_ev_chargers() -> list[dict[str, Any]]:
    """Return all configured EV chargers with live sensors, goal, progress, status."""
    config = load_yaml("config.yaml")
    ev_chargers_cfg: list[dict[str, Any]] = config.get("ev_chargers", []) or []
    ev_voltage = nominal_voltage_v(config)
    state_by_id = _load_ev_state()
    schedule = _load_schedule()
    schedule_meta = _load_schedule_meta(schedule)
    goal_diagnostics = cast(
        "dict[str, dict[str, Any]]", schedule_meta.get("ev_goal_diagnostics") or {}
    )
    now = datetime.now(UTC)
    planned_starts = _first_planned_starts(schedule, now)
    # The executor runs manual charges; the state file is only its mirror
    # and is read when no executor instance exists.
    from backend.api.routers.executor import get_executor_instance

    executor = get_executor_instance()
    live_manual: dict[str, dict[str, Any]] | None = (
        executor.get_ev_manual_charge_status() if executor is not None else None
    )

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

    async def _safe_raw_state(entity_id: str) -> Any:
        if not entity_id:
            return None
        try:
            state = await get_ha_entity_state(entity_id)
        except Exception as exc:
            logger.warning("Failed to read HA sensor %s: %s", entity_id, exc)
            return None
        return state.get("state") if isinstance(state, dict) else None

    async def _build_charger(ev: dict[str, Any]) -> dict[str, Any] | None:
        if not ev.get("enabled", True):
            return None
        charger_id = str(ev.get("id", ""))

        plug_sensor = str(ev.get("plug_sensor", "") or "")
        power_kw, soc_percent, raw_plug, raw_switch = await asyncio.gather(
            _safe_kw(str(ev.get("sensor", ""))),
            _safe_float(str(ev.get("soc_sensor", ""))),
            _safe_raw_state(plug_sensor),
            _safe_raw_state(str(ev.get("switch_entity", "") or "")),
        )
        # unavailable/unknown plug or switch = charger unreachable, not unplugged;
        # the plug state then reports the last known reading.
        plugged_in: bool | None = None
        plug_unreachable = False
        if plug_sensor and raw_plug is not None:
            plugged_in, plug_unreachable = resolve_plug_state(
                charger_id,
                raw_plug,
                ev.get("plugged_in_states") or DEFAULT_EV_PLUGGED_IN_STATES,
            )
        unreachable = plug_unreachable or is_unreachable_state(raw_switch)

        entry = state_by_id.get(charger_id, {})
        # The persisted manual charge shares the entry; it is not a goal.
        manual_charge = _manual_charge_view(
            live_manual.get(charger_id) if live_manual is not None else entry.get("manual_charge")
        )
        persisted = {k: v for k, v in entry.items() if k != "manual_charge"}

        max_kw = charger_max_kw(ev, ev_voltage)
        # A charger whose power cannot be derived is disabled for planning;
        # surface why (never silently drop it from the card).
        problem = charger_disabled_reason(ev, ev_voltage)
        disabled_reason = problem[1] if problem is not None else None

        # Same default as the executor (EVChargerDeviceConfig.type).
        charger_type = str(ev.get("type") or "binary").lower()
        # Manual-charge current range (current-type only); max falls back to
        # min exactly like the executor does.
        current_limits: dict[str, int | None] = {"min_current_a": None, "max_current_a": None}
        if charger_type == "current":
            min_current_a = int(ev.get("min_current_a", 6))
            max_current_raw = ev.get("max_current_a")
            current_limits = {
                "min_current_a": min_current_a,
                "max_current_a": int(max_current_raw)
                if max_current_raw is not None
                else min_current_a,
            }

        externally_controlled = False
        if charger_type == "binary":
            externally_controlled = not bool(ev.get("switch_entity"))
        else:
            externally_controlled = not bool(ev.get("current_entity"))

        if not persisted:
            # No goal set for this charger → idle with null goal-progress; live sensors only.
            return {
                "id": charger_id,
                "name": ev.get("name", charger_id),
                "plugged_in": plugged_in,
                "unreachable": unreachable,
                "soc_percent": round(soc_percent, 1) if soc_percent is not None else None,
                "power_kw": round(power_kw, 3) if power_kw is not None else None,
                "target_soc_percent": None,
                "ready_by": None,
                "repeat": None,
                "deadline": None,
                "required_kwh": None,
                "delivered_kwh": None,
                "remaining_kwh": None,
                "planned_by_day": [],
                "deferral_price_source": None,
                "keep_on_after_target": bool(ev.get("keep_on_after_target", False)),
                "ha_ready_by_entity": ev.get("ha_ready_by_entity"),
                "ha_target_soc_entity": ev.get("ha_target_soc_entity"),
                "type": charger_type,
                **current_limits,
                "n_days": None,
                "ready_by_date": None,
                "status": "idle",
                "shortfall_kwh": None,
                "shortfall_reason": None,
                "source": None,
                "externally_controlled": externally_controlled,
                "last_updated": None,
                "last_planned_at": None,
                "anchor_date": None,
                "plan_pending": _plan_pending(charger_id, {}),
                "assumed_plugged": False,
                "planned_start": None,
                "manual_charge": manual_charge,
                "disabled_reason": disabled_reason,
            }

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
                max_kw,
                now,
            )

        shortfall_kwh: float | None = None
        shortfall_reason: str | None = None
        if status == "on_track":
            at_risk = _active_goal_shortfall(goal_diagnostics.get(charger_id), persisted)
            if at_risk is not None:
                status = "at_risk"
                shortfall_kwh = float(at_risk["shortfall_kwh"])
                shortfall_reason = at_risk.get("reason")

        return {
            "id": charger_id,
            "name": ev.get("name", charger_id),
            "plugged_in": plugged_in,
            "unreachable": unreachable,
            "soc_percent": round(soc_percent, 1) if soc_percent is not None else None,
            "power_kw": round(power_kw, 3) if power_kw is not None else None,
            "target_soc_percent": persisted.get("target_soc_percent"),
            "ready_by": persisted.get("ready_by"),
            "repeat": persisted.get("repeat"),
            "deadline": persisted.get("deadline"),
            "required_kwh": persisted.get("required_kwh"),
            "delivered_kwh": persisted.get("delivered_kwh"),
            "remaining_kwh": persisted.get("remaining_kwh"),
            "planned_by_day": _planned_by_day_view(persisted.get("planned_by_day")),
            "deferral_price_source": persisted.get("deferral_price_source"),
            "keep_on_after_target": bool(persisted.get("keep_on_after_target", False)),
            "ha_ready_by_entity": ev.get("ha_ready_by_entity"),
            "ha_target_soc_entity": ev.get("ha_target_soc_entity"),
            "type": charger_type,
            **current_limits,
            "n_days": persisted.get("n_days"),
            "ready_by_date": persisted.get("ready_by_date"),
            "status": status,
            "shortfall_kwh": shortfall_kwh,
            "shortfall_reason": shortfall_reason,
            "max_import_kw": (goal_diagnostics.get(charger_id) or {}).get("max_import_kw")
            if shortfall_reason
            else None,
            "source": persisted.get("source"),
            "externally_controlled": externally_controlled,
            "last_updated": persisted.get("last_updated"),
            "last_planned_at": persisted.get("last_planned_at"),
            "anchor_date": persisted.get("anchor_date"),
            "plan_pending": _plan_pending(charger_id, persisted),
            "assumed_plugged": bool(persisted.get("assumed_plugged", False))
            and plugged_in is not True,
            "planned_start": planned_starts.get(charger_id),
            "manual_charge": manual_charge,
            "disabled_reason": disabled_reason,
        }

    results = await asyncio.gather(*(_build_charger(ev) for ev in ev_chargers_cfg))
    return [charger for charger in results if charger is not None]


# --- Manual charge (ev-manual-charge) ---


class EVManualChargeBody(BaseModel):
    target_soc: int = Field(ge=1, le=100)
    current_a: int | None = Field(default=None)


def _manual_charge_view(raw: Any) -> dict[str, Any] | None:
    """Public shape of a manual charge (executor or persisted); None when absent/malformed."""
    if not isinstance(raw, dict):
        return None
    data = cast("dict[str, Any]", raw)
    if data.get("target_soc") is None or data.get("started_at") is None:
        return None
    return {
        "target_soc": data.get("target_soc"),
        "current_a": data.get("current_a"),
        "started_at": data.get("started_at"),
    }


def _enabled_charger_cfg(charger_id: str) -> dict[str, Any]:
    config = load_yaml("config.yaml")
    ev_chargers_cfg: list[dict[str, Any]] = config.get("ev_chargers", []) or []
    charger_cfg = next(
        (c for c in ev_chargers_cfg if c.get("id") == charger_id and c.get("enabled", True)),
        None,
    )
    if charger_cfg is None:
        raise HTTPException(status_code=404, detail=f"EV charger {charger_id} not found")
    return charger_cfg


def _executor_or_503() -> Any:
    from backend.api.routers.executor import get_executor_instance

    executor = get_executor_instance()
    if executor is None:
        raise HTTPException(status_code=503, detail="Executor unavailable")
    return executor


@router.post(
    "/chargers/{id}/manual-charge",
    summary="Start EV Manual Charge",
    description=(
        "Charge the car on this charger now until it reaches ``target_soc`` (1-100). "
        "``current_a`` is optional and only valid on current-type chargers "
        "(default ``max_current_a``). Rejected when the car is not connected, its "
        "plug state or SoC is unknown, or the target is already reached. Ends by itself at the "
        "target, on unplug, or after 24 h; the charging goal is not changed."
    ),
)
async def start_ev_manual_charge(id: str, body: EVManualChargeBody) -> dict[str, Any]:
    charger_cfg = _enabled_charger_cfg(id)
    executor = _executor_or_503()

    async def _raw_state(entity_id: str) -> str | None:
        state = await get_ha_entity_state(entity_id)
        raw = state.get("state") if isinstance(state, dict) else None
        return str(raw) if raw is not None else None

    live = await read_ev_live_state(
        id,
        _raw_state,
        soc_sensor=str(charger_cfg.get("soc_sensor") or ""),
        plug_sensor=str(charger_cfg.get("plug_sensor") or ""),
        plugged_in_states=charger_cfg.get("plugged_in_states") or DEFAULT_EV_PLUGGED_IN_STATES,
    )

    try:
        return executor.set_ev_manual_charge(
            id,
            body.target_soc,
            body.current_a,
            current_soc_percent=live.soc_percent,
            plug_state=live.plug,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/chargers/{id}/manual-charge",
    summary="Stop EV Manual Charge",
    description="Stops the charger's manual charge; the plan takes over on the next tick.",
)
async def stop_ev_manual_charge(id: str) -> dict[str, Any]:
    _enabled_charger_cfg(id)
    executor = _executor_or_503()
    return executor.clear_ev_manual_charge(id)
