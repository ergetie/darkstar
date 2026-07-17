"""
Planner Pipeline

Main orchestrator for the modular planner pipeline.
Coordinates Input → Strategy → Solver → Output flow.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pandas as pd
import pytz

if TYPE_CHECKING:
    from datetime import date, datetime


from backend.core.ev_goal import resolve_next_ready_by
from backend.core.version import get_version
from backend.learning.store import LearningStore
from planner.errors import PlannerError, PlannerErrorCode
from planner.inputs.data_prep import apply_safety_margins, prepare_df
from planner.inputs.learning import load_learning_overlays
from planner.inputs.weather import fetch_temperature_forecast
from planner.output.schedule import save_schedule_to_json
from planner.output.soc_target import apply_soc_target_percent
from planner.preflight import run_preflight
from planner.solver.adapter import (
    config_to_kepler_config,
    derive_min_power_kw,
    kepler_result_to_dataframe,
    planner_to_kepler_input,
)
from planner.solver.kepler import KeplerSolver
from planner.strategy.manual_plan import apply_manual_plan
from planner.strategy.multi_day_planner import MultiDayPlanner
from planner.strategy.s_index import (
    calculate_dynamic_s_index,
    calculate_probabilistic_s_index,
    calculate_safety_floor,
)
from planner.vacation_state import load_last_anti_legionella, save_last_anti_legionella


def _ev_delivered_today_kwh(db_path: str, charger_id: str, tz: pytz.BaseTzInfo) -> float:
    """Fetch aggregate EV charging energy recorded today from slot_observations.

    The table currently stores only aggregate ``ev_charging_kwh``; this is used
    as a best-effort delivered-so-far value for the single/primary charger case.
    """
    import sqlite3
    from datetime import datetime, time

    try:
        conn = sqlite3.connect(db_path, timeout=10)
    except Exception:
        return 0.0

    try:
        today = datetime.now(tz).date()
        start_local = tz.localize(datetime.combine(today, time.min))
        start_iso = start_local.isoformat()
        cursor = conn.execute(
            "SELECT SUM(ev_charging_kwh) FROM slot_observations WHERE slot_start >= ?",
            (start_iso,),
        )
        row = cursor.fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0
    except Exception:
        return 0.0
    finally:
        conn.close()


def _calculate_required_kwh(
    charger_cfg: dict[str, Any],
    ha_state: dict[str, Any],
    db_path: str | None,
    tz: pytz.BaseTzInfo,
    *,
    single_enabled_charger: bool = True,
) -> float:
    """Compute remaining kWh required to reach target SoC.

    When a live SoC reading is available, ``required_kwh = max(0, (target -
    current_soc)/100 * capacity)`` — the live reading already reflects
    charging progress, so delivered-today is NOT subtracted on top of it
    (that would double-count progress and leave the car short of target).

    Only when SoC is unavailable (sensor missing/unreadable — distinguished
    from a real 0.0 reading by ``ha_state["soc_percent"]`` being ``None``)
    does the calculation fall back to ``target/100 * capacity -
    delivered_today``. That fallback's ``slot_observations.ev_charging_kwh``
    column is an unattributable aggregate across all chargers, so it is only
    applied when exactly one charger is enabled; with multiple SoC-less
    chargers, nothing is subtracted (a warning is logged instead).
    """
    target_soc = float(charger_cfg.get("target_soc_percent", 80))
    capacity = float(charger_cfg.get("battery_capacity_kwh") or 0.0)
    current_soc = ha_state.get("soc_percent")

    if current_soc is not None:
        return max(0.0, (target_soc - float(current_soc)) / 100.0 * capacity)

    required = max(0.0, target_soc / 100.0 * capacity)
    if not db_path:
        return required

    if not single_enabled_charger:
        logger.warning(
            "EV %s: SoC unavailable with multiple EV chargers enabled - "
            "delivered-today (slot_observations.ev_charging_kwh) is an "
            "unattributable aggregate; not subtracting.",
            charger_cfg.get("id", ""),
        )
        return required

    charger_id = str(charger_cfg.get("id", ""))
    delivered = _ev_delivered_today_kwh(db_path, charger_id, tz)
    return max(0.0, required - delivered)


def _max_daily_kwh_for_deadline(
    max_power_kw: float,
    now: datetime,
    deadline: datetime,
    tz: pytz.BaseTzInfo,
) -> list[float]:
    """Return per-day max energy (kWh) from today until ``deadline``."""
    from datetime import datetime as _datetime, time

    today = now.date()
    deadline_date = deadline.date()
    from datetime import timedelta

    days: list[date] = []
    d = today
    while d <= deadline_date:
        days.append(d)
        d += timedelta(days=1)

    max_daily: list[float] = []
    for i, day in enumerate(days):
        if i == 0 and day == today:
            start = now
            end_of_day = tz.localize(_datetime.combine(day, time(23, 59, 59)))
            end = min(deadline, end_of_day)
        elif day == deadline_date:
            start = tz.localize(_datetime.combine(day, time.min))
            end = deadline
        else:
            start = tz.localize(_datetime.combine(day, time.min))
            end = tz.localize(_datetime.combine(day, time(23, 59, 59)))
        hours = max(0.0, (end - start).total_seconds() / 3600.0)
        max_daily.append(max_power_kw * hours)

    return max_daily


def _compute_daily_ev_quota(
    charger_cfg: dict[str, Any],
    deadline: datetime,
    required_kwh: float,
    upcoming_spots: dict[int, float],
    now: datetime,
    tz: pytz.BaseTzInfo,
) -> tuple[float | None, dict[date, float] | None]:
    """Compute today's quota and full schedule when spreading is active.

    Spreading only applies when the deadline is more than one calendar day
    away and a price forecast exists. Otherwise returns ``(None, None)`` so
    Kepler optimises within the known day-ahead horizon without a quota.
    """
    from datetime import timedelta

    if required_kwh <= 0 or not upcoming_spots:
        return None, None

    # More than one day out means the deadline is at least tomorrow and there
    # is at least one full day between now and the deadline.
    time_to_deadline = deadline - now
    if time_to_deadline <= timedelta(days=1):
        return None, None

    max_power_kw = float(charger_cfg.get("max_power_kw") or 7.4)
    max_daily = _max_daily_kwh_for_deadline(max_power_kw, now, deadline, tz)

    # Smallest energy the solver can schedule in one 15-min slot: derived min
    # power for `type: current` chargers, max power for `type: binary`
    # (`derive_min_power_kw` already returns max_power_kw for binary).
    control_type = str(charger_cfg.get("type", "binary")).lower()
    min_power_kw = derive_min_power_kw(charger_cfg, control_type, max_power_kw)
    min_chunk_kwh = min_power_kw * 0.25

    quota_schedule = MultiDayPlanner.compute_quota(
        remaining_kwh=required_kwh,
        deadline=deadline,
        daily_prices=upcoming_spots,
        max_daily_kwh=max_daily,
        min_daily_fraction=0.1,
        now=now,
        min_chunk_kwh=min_chunk_kwh,
    )

    if not quota_schedule:
        return None, None

    today = now.date()
    today_quota = quota_schedule.get(today)
    if today_quota is None:
        return None, None

    return float(today_quota), quota_schedule


def _ev_charger_status(
    plugged_in: bool,
    deadline: datetime | None,
    required_kwh: float | None,
    max_power_kw: float,
    now: datetime,
) -> str:
    """Classify a charger per ``status ∈ {on_track, behind, complete, idle}``.

    ``on_track``  — target deliverable before the deadline at the configured power.
    ``behind``    — physically cannot reach the target in the remaining time.
    ``complete``  — required energy already met (no charge needed).
    ``idle``      — not plugged in, or no active goal/deadline.
    """

    if not plugged_in or deadline is None or required_kwh is None:
        return "idle"
    if required_kwh <= 0.0:
        return "complete"
    seconds_left = (deadline - now).total_seconds()
    if seconds_left <= 0.0:
        return "behind"
    deliverable = max_power_kw * (seconds_left / 3600.0)
    return "on_track" if deliverable + 1e-6 >= required_kwh else "behind"


def _apply_keep_on_after_target(
    result: Any,
    ev_states: list[dict[str, Any]],
    ev_chargers_cfg: list[dict[str, Any]],
    now: datetime,
) -> None:
    """Post-solve keep-on-standby flag for ``keep_on_after_target``.

    When a charger has ``keep_on_after_target=True`` and the goal target SoC is
    100% and live SoC is already at 100%, the solver schedules no EV slots
    (``required_kwh=0``). This sets ``slot.ev_keep_on[charger_id] = True`` on
    each upcoming slot (``now < end_time <= deadline``) so the executor keeps
    the charger connected as a standby supply for EV ambient/cabin/
    preconditioning loads — the EV's onboard charger self-gates actual battery
    draw past 100%. The flag carries no planned energy: ``ev_charger_results``/
    ``ev_charge_kw`` are left untouched (0 from the solver), so schedule
    totals stay energy-consistent. After the ready-by deadline the charger
    idles (no flag), matching the agreed window: target-met → deadline. Gated
    on target=100 to avoid overcharging chemistries sensitive to repeated
    full-top-ups.
    """
    cfg_by_id = {str(c.get("id", "")): c for c in ev_chargers_cfg}
    keep_on_map: dict[str, Any] = {}
    for state in ev_states:
        if not state.get("keep_on_after_target"):
            continue
        charger_id = str(state.get("id", ""))
        cfg = cfg_by_id.get(charger_id, {})
        if int(cfg.get("target_soc_percent", 0) or 0) != 100:
            continue
        if float(state.get("soc_percent", 0.0) or 0.0) < 100.0:
            continue
        deadline = state.get("deadline")
        if deadline is None or deadline <= now:
            continue
        max_power_kw = float(cfg.get("max_power_kw") or 0.0)
        if max_power_kw <= 0:
            continue
        keep_on_map[charger_id] = deadline

    if not keep_on_map:
        return

    for slot in result.slots:
        if slot.end_time <= now:
            continue
        for charger_id, deadline in keep_on_map.items():
            if slot.end_time <= deadline:
                slot.ev_keep_on[charger_id] = True
    logger.info(
        "keep_on_after_target: standby flag active for %d charger(s) until ready-by",
        len(keep_on_map),
    )


def _warn_on_zero_scheduled_active_goals(
    result: Any,
    ev_states: list[dict[str, Any]],
    ev_chargers_cfg: list[dict[str, Any]],
) -> None:
    """Loudly report an active EV goal that produced zero scheduled energy.

    A charger with ``required_kwh > 0`` and a resolved deadline should never
    silently convert entirely to shortfall — log a WARNING naming the
    charger, the required kWh, the per-day quota split, and the minimum
    schedulable chunk so quota/feasibility interactions (design D1-D4) are
    never invisible.
    """
    cfg_by_id = {str(c.get("id", "")): c for c in ev_chargers_cfg}

    for state in ev_states:
        required_kwh = state.get("required_kwh")
        deadline = state.get("deadline")
        if required_kwh is None or deadline is None or required_kwh <= 0:
            continue

        charger_id = str(state.get("id", ""))
        total_scheduled_kwh = sum(
            s.ev_charger_results.get(charger_id, 0.0)
            * ((s.end_time - s.start_time).total_seconds() / 3600.0)
            for s in result.slots
        )
        if total_scheduled_kwh > 1e-6:
            continue

        cfg = cfg_by_id.get(charger_id, {})
        control_type = str(cfg.get("type", "binary")).lower()
        max_power_kw = float(cfg.get("max_power_kw") or 0.0)
        min_power_kw = derive_min_power_kw(cfg, control_type, max_power_kw)
        min_chunk_kwh = min_power_kw * 0.25

        quota_schedule = cast("dict[Any, float] | None", state.get("quota_schedule"))
        quota_by_day = {str(k): round(v, 2) for k, v in (quota_schedule or {}).items()}
        logger.warning(
            "EV %s: active goal (required=%.2f kWh, deadline=%s) produced ZERO "
            "scheduled charging — quota_by_day=%s, min_chunk_kwh=%.3f",
            charger_id,
            required_kwh,
            deadline,
            quota_by_day,
            min_chunk_kwh,
        )


def merge_ev_goals_from_state(
    ev_chargers_cfg_raw: list[dict[str, Any]],
    ev_state_data: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge each charger's config (hardware facts) with its goal from the state file.

    Goals live ONLY in the state file (dashboard/API/HA are the sole source of
    truth) — a charger with no state-file goal has no goal (all goal fields
    are ``None``), never a config fallback.
    """
    merged: list[dict[str, Any]] = []
    for ev_cfg_item in ev_chargers_cfg_raw:
        charger_id = ev_cfg_item.get("id", "")
        charger_state = ev_state_data.get(charger_id, {})
        goal_cfg = dict(ev_cfg_item)
        if charger_state and charger_state.get("target_soc_percent") is not None:
            goal_cfg["target_soc_percent"] = charger_state.get("target_soc_percent")
            goal_cfg["ready_by"] = charger_state.get("ready_by")
            goal_cfg["repeat"] = charger_state.get("repeat")
            goal_cfg["ready_by_date"] = charger_state.get("ready_by_date")
            goal_cfg["n_days"] = charger_state.get("n_days")
            goal_cfg["last_updated"] = charger_state.get("last_updated")
            goal_cfg["keep_on_after_target"] = bool(
                charger_state.get("keep_on_after_target", False)
            )
            logger.debug(
                "EV %s: using goal from state file (target_soc_percent=%s, ready_by=%s, repeat=%s)",
                charger_id,
                goal_cfg["target_soc_percent"],
                goal_cfg["ready_by"],
                goal_cfg["repeat"],
            )
        else:
            goal_cfg["target_soc_percent"] = None
            goal_cfg["ready_by"] = None
            goal_cfg["repeat"] = None
            goal_cfg["ready_by_date"] = None
            goal_cfg["n_days"] = None
            goal_cfg["last_updated"] = None
            goal_cfg["keep_on_after_target"] = False
            logger.debug("EV %s: no goal set in the dashboard - charger inert", charger_id)
        merged.append(goal_cfg)
    return merged


def _persist_ev_multi_day_state(
    ev_states: list[dict[str, Any]],
    ev_chargers_cfg: list[dict[str, Any]],
    sqlite_path: str,
    tz: pytz.BaseTzInfo,
    now: datetime,
) -> None:
    """Merge per-charger progress into ``data/ev_multi_day_state.json``.

    Goal fields (``target_soc_percent``, ``ready_by``, ``repeat``,
    ``ready_by_date``, ``n_days``, ``keep_on_after_target``, ``source``,
    ``last_updated``) belong to the dashboard/API/HA and are preserved
    verbatim — the planner never invents or derives a goal from config, and
    never touches ``last_updated`` (it anchors ``every_n_days``). Progress
    fields (``deadline``, ``required_kwh``, ``delivered_kwh``,
    ``remaining_kwh``, ``daily_quota_kwh``, ``quota_schedule``, ``status``,
    ``last_planned_at``) are refreshed for chargers processed this run.
    Chargers with no goal, or not processed this run (disabled/skipped), keep
    their existing entry untouched — this is a merge, not a replace.
    """
    from backend.core.ev_state import update_ev_state

    cfg_by_id = {str(c.get("id", "")): c for c in ev_chargers_cfg}

    def _mutate(existing_state: dict[str, dict[str, Any]]) -> None:
        for state in ev_states:
            charger_id = str(state.get("id", ""))
            existing_charger = existing_state.get(charger_id, {})

            if existing_charger.get("target_soc_percent") is None:
                # No goal set for this charger (dashboard is the sole source of
                # truth) — nothing to persist.
                continue

            cfg = cfg_by_id.get(charger_id, {})
            deadline = state.get("deadline")
            required_kwh = state.get("required_kwh")
            max_power_kw = float(cfg.get("max_power_kw") or 7.4)
            capacity = float(cfg.get("battery_capacity_kwh") or 0.0)
            current_soc = float(state.get("soc_percent") or 0.0)

            delivered_kwh = 0.0
            if sqlite_path:
                delivered_kwh = _ev_delivered_today_kwh(sqlite_path, charger_id, tz)
            remaining_kwh = None if required_kwh is None else max(0.0, required_kwh)

            quota_schedule = state.get("quota_schedule")
            schedule_json: dict[str, float] | None = None
            if quota_schedule:
                schedule_json = {str(d): round(float(v), 3) for d, v in quota_schedule.items()}

            dq = state.get("daily_quota_kwh")

            existing_state[charger_id] = {
                # Goal fields: preserved verbatim, never derived from config.
                "target_soc_percent": existing_charger.get("target_soc_percent"),
                "ready_by": existing_charger.get("ready_by"),
                "repeat": existing_charger.get("repeat"),
                "ready_by_date": existing_charger.get("ready_by_date"),
                "n_days": existing_charger.get("n_days"),
                "keep_on_after_target": bool(existing_charger.get("keep_on_after_target", False)),
                "source": existing_charger.get("source"),
                "last_updated": existing_charger.get("last_updated"),
                # Progress fields: refreshed every run this charger is processed.
                "deadline": deadline.isoformat() if deadline else None,
                "required_kwh": round(float(required_kwh), 3) if required_kwh is not None else None,
                "delivered_kwh": round(delivered_kwh, 3),
                "remaining_kwh": round(float(remaining_kwh), 3)
                if remaining_kwh is not None
                else None,
                "current_soc_percent": round(current_soc, 2),
                "battery_capacity_kwh": capacity,
                "daily_quota_kwh": round(float(dq), 3) if dq is not None else None,
                "quota_schedule": schedule_json,
                "status": _ev_charger_status(
                    bool(state.get("plugged_in", False)),
                    deadline,
                    required_kwh,
                    max_power_kw,
                    now,
                ),
                "last_planned_at": now.isoformat(),
            }

    try:
        update_ev_state(_mutate)
        logger.debug("Persisted EV multi-day state for %d charger(s)", len(ev_states))
    except Exception as exc:
        logger.warning("Failed to persist EV multi-day state: %s", exc)


logger = logging.getLogger("darkstar.planner")


def _fetch_price_floor_inputs_sync(
    db_path: str, timezone_name: str
) -> tuple[dict[int, float], float | None]:
    """
    Fetch price floor inputs for the S-Index from the learning DB (Module 3).

    Returns:
        Tuple of (upcoming_daily_avg_spots, trailing_avg_spot):
        - upcoming_daily_avg_spots: days-ahead offset (int) -> daily avg spot_p50
          for D+1..D+7. Computed from the latest issue per slot_start, grouped by
          calendar date in the configured timezone.
        - trailing_avg_spot: 14-day trailing average of export_price_sek_kwh from
          slot_observations (>=2 distinct calendar days required); None if absent.
    """
    import sqlite3
    from datetime import datetime, time, timedelta

    tz = pytz.timezone(timezone_name)
    now = datetime.now(tz)
    today = now.date()

    upcoming: dict[int, float] = {}
    trailing: float | None = None

    try:
        conn = sqlite3.connect(db_path, timeout=30)
    except Exception as exc:
        logger.warning("Price floor inputs: cannot open DB: %s", exc)
        return upcoming, trailing

    try:
        conn.row_factory = sqlite3.Row

        # --- Today's (offset 0) remaining-slots avg spot p50, plus D+1..D+7 ---
        start_local = tz.localize(datetime.combine(today, time.min))
        end_local = tz.localize(datetime.combine(today + timedelta(days=8), time.min))
        start_iso = start_local.isoformat()
        end_iso = end_local.isoformat()

        cursor = conn.execute(
            """
            SELECT slot_start, issue_timestamp, spot_p50
            FROM price_forecasts
            WHERE slot_start >= ? AND slot_start < ?
              AND spot_p50 IS NOT NULL
            ORDER BY slot_start
            """,
            (start_iso, end_iso),
        )
        best_per_slot: dict[str, dict[str, Any]] = {}
        for r in cursor.fetchall():
            key = r["slot_start"]
            existing = best_per_slot.get(key)
            if existing is None or (r["issue_timestamp"] or "") > existing["issue_timestamp"]:
                best_per_slot[key] = {
                    "slot_start": key,
                    "issue_timestamp": r["issue_timestamp"] or "",
                    "spot_p50": float(r["spot_p50"]),
                }

        # Group by calendar date (local tz), then average per day. Offset 0
        # (today) only counts remaining slots (slot_start >= now) — past
        # cheap morning slots must not inflate today's attractiveness.
        per_day: dict[int, list[float]] = {}
        for row in best_per_slot.values():
            try:
                slot_dt = datetime.fromisoformat(row["slot_start"]).astimezone(tz)
            except (TypeError, ValueError):
                continue
            offset = (slot_dt.date() - today).days
            if offset == 0 and slot_dt < now:
                continue
            if 0 <= offset <= 7:
                per_day.setdefault(offset, []).append(row["spot_p50"])

        for offset, spots in per_day.items():
            if spots:
                upcoming[offset] = sum(spots) / len(spots)

        # --- Trailing 14-day avg export price_sek_kwh (>=2 distinct days) ---
        trailing_start = (today - timedelta(days=14)).isoformat()
        cursor = conn.execute(
            """
            SELECT slot_start, export_price_sek_kwh
            FROM slot_observations
            WHERE slot_start >= ? AND export_price_sek_kwh IS NOT NULL
            """,
            (trailing_start,),
        )
        values: list[float] = []
        distinct_dates: set[date] = set()
        for r in cursor.fetchall():
            try:
                slot_dt = datetime.fromisoformat(r["slot_start"])
                distinct_dates.add(slot_dt.astimezone(tz).date())
            except (TypeError, ValueError):
                continue
            values.append(float(r["export_price_sek_kwh"]))

        if len(distinct_dates) >= 2 and values:
            trailing = sum(values) / len(values)
    except Exception as exc:
        logger.warning("Price floor inputs: DB query failed: %s", exc)
        return upcoming, trailing
    finally:
        conn.close()

    return upcoming, trailing


async def fetch_price_floor_inputs(
    db_path: str, timezone_name: str
) -> tuple[dict[int, float], float | None]:
    """
    Async wrapper around the synchronous price-floor-inputs DB query.

    The synchronous query is offloaded to a thread (matching the established
    `asyncio.to_thread` pattern used by the price-forecast API router) so the
    event loop is never blocked on a long-running SQLite read.
    """
    return await asyncio.to_thread(_fetch_price_floor_inputs_sync, db_path, timezone_name)


def _calculate_excess_pv_flags(
    kepler_slots: list[Any],
    water_heaters: list[Any],
    ev_chargers: list[Any],
    df: pd.DataFrame,
) -> list[bool]:
    """Pre-calculate per-slot excess PV flags from raw forecasts.

    excess[t] = max(0, pv_forecast[t] - load_forecast[t] - min_water_heat_forecast[t] - min_ev_forecast[t]) > 0

    Returns list of booleans, one per slot.
    """

    T = len(kepler_slots)
    if T == 0:
        return []

    slot_hours_list: list[float] = []
    for s in kepler_slots:
        duration = (s.end_time - s.start_time).total_seconds() / 3600.0
        slot_hours_list.append(duration)

    avg_slot_hours = sum(slot_hours_list) / len(slot_hours_list) if slot_hours_list else 0.25

    # Minimum water heating per slot (sum across all heaters, min_kwh_per_day spread evenly)
    min_water_heat_per_slot = 0.0
    for wh in water_heaters:
        kwh_per_slot = wh.power_kw * avg_slot_hours
        if kwh_per_slot > 0:
            min_water_heat_per_slot += wh.min_kwh_per_day / (24.0 / avg_slot_hours)

    # Minimum EV charging per slot (EVs do not have a baseline daily maintenance load like water heaters)
    min_ev_per_slot = 0.0

    flags: list[bool] = []
    for t in range(T):
        pv_kwh = kepler_slots[t].pv_kwh
        load_kwh = kepler_slots[t].load_kwh
        excess = pv_kwh - load_kwh - min_water_heat_per_slot - min_ev_per_slot
        flags.append(excess > 0)

    return flags


class PlannerPipeline:
    """
    Orchestrator for the modular planner pipeline.

    Modes:
        - "full": Aurora overlays + Strategy + Kepler (production)
        - "baseline": Kepler only, no Aurora overlays (for A/B comparison)
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize the pipeline with configuration.

        Args:
            config: Configuration dictionary (from config.yaml)
        """
        self.config = config
        self._validate_config()

    def _validate_config(self) -> None:
        """Validate critical configuration values."""
        required_sections = ["battery", "battery_economics"]
        for section in required_sections:
            if section not in self.config:
                raise ValueError(f"Missing required config section: {section}")

        # Validate system profile toggle consistency (REV LCL01)
        system_cfg = self.config.get("system", {})
        water_cfg = self.config.get("water_heating", {})
        battery_cfg = self.config.get("battery", {})

        # Battery: ERROR if enabled but no capacity (breaks MILP solver)
        if system_cfg.get("has_battery", True):
            capacity = float(battery_cfg.get("capacity_kwh", 0.0))
            if capacity <= 0:
                raise ValueError(
                    "Config error: system.has_battery is true but "
                    "battery.capacity_kwh is not set (or is 0). "
                    "Set battery.capacity_kwh or set system.has_battery to false."
                )

        # Water heater: WARNING only (doesn't break system, just disables feature)
        # REV F66b: Check new ARC15 water_heaters[] array, fallback to legacy water_heating
        if system_cfg.get("has_water_heater", True):
            water_heaters = self.config.get("water_heaters", [])
            if water_heaters:
                # New ARC15 structure - sum power from enabled heaters
                enabled_heaters = [wh for wh in water_heaters if wh.get("enabled", True)]
                power_kw = sum(float(wh.get("power_kw", 0.0)) for wh in enabled_heaters)
            else:
                # Legacy structure
                power_kw = float(water_cfg.get("power_kw", 0.0))

            if power_kw <= 0:
                logger.warning(
                    "Config warning: has_water_heater=true but water heater power is 0. "
                    "Water heating optimization is disabled."
                )

        # Solar: WARNING only (doesn't break system, just zeros PV forecasts)
        # REV F66b: Check new solar_arrays[] array, fallback to legacy solar_array
        if system_cfg.get("has_solar", True):
            solar_arrays = system_cfg.get("solar_arrays", [])
            if solar_arrays:
                # New structure - sum kwp from all arrays
                kwp = sum(float(sa.get("kwp", 0.0)) for sa in solar_arrays)
            else:
                # Legacy structure
                solar_cfg = system_cfg.get("solar_array", {})
                kwp = float(solar_cfg.get("kwp", 0.0))

            if kwp <= 0:
                logger.warning(
                    "Config warning: has_solar=true but solar kwp is 0. PV forecasts will be zero."
                )

    def _apply_overrides(self, config: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        """Apply configuration overrides recursively."""
        new_config = copy.deepcopy(config)

        def update_recursive(d: dict[str, Any], u: dict[str, Any]) -> dict[str, Any]:
            for k, v in u.items():
                if isinstance(v, dict):
                    d[k] = update_recursive(d.get(k, {}), v)  # type: ignore[arg-type]
                else:
                    d[k] = v
            return d

        return update_recursive(new_config, overrides)

    async def generate_schedule(
        self,
        input_data: dict[str, Any],
        overrides: dict[str, Any] | None = None,
        mode: str = "full",
        save_to_file: bool = True,
        record_training_episode: bool = False,
        now_override: datetime | None = None,
        ev_plug_override_charger_id: str | None = None,
    ) -> pd.DataFrame:
        """
        Generate an optimal battery schedule.

        Args:
            input_data: Dictionary with price_data, forecast_data, initial_state
            overrides: Optional configuration overrides
            mode: "full" (Aurora + Kepler) or "baseline" (Kepler only)
            save_to_file: Whether to save schedule.json
            record_training_episode: Whether to log training episode (RL)
            now_override: Override current time for simulation/replay

        Returns:
            DataFrame with the complete schedule
        """
        logger.info("Darkstar %s — PlannerPipeline.generate_schedule(mode=%s)", get_version(), mode)

        # 1. Configuration & Overrides
        active_config = self.config
        if overrides:
            active_config = self._apply_overrides(self.config, overrides)

        # System Profile Toggles (Rev O1)
        system_cfg = active_config.get("system", {})
        has_solar = system_cfg.get("has_solar", True)
        has_battery = system_cfg.get("has_battery", True)
        has_water_heater = system_cfg.get("has_water_heater", True)
        water_cfg = active_config.get("water_heating", {})

        logger.info(
            "System profile: solar=%s, battery=%s, water=%s",
            has_solar,
            has_battery,
            has_water_heater,
        )

        # 2. Load Inputs
        # Load learning overlays (PV/Load bias, S-Index base)
        learning_overlays = {}
        if mode == "full":
            learning_overlays = await load_learning_overlays(active_config.get("learning", {}))

        # Rev WH2: Load previous schedule to check for active water heating (Mid-block locking)
        previous_schedule: list[dict[str, Any]] = []
        try:
            import json

            schedule_path = Path("schedule.json")
            if schedule_path.exists():
                with schedule_path.open() as f:
                    data = json.load(f)
                    previous_schedule = data.get("schedule", [])
        except Exception as e:
            logger.warning("Failed to load previous schedule for water locking: %s", e)

        # Prepare DataFrame (merge prices + forecasts)
        timezone_name = active_config.get("timezone", "Europe/Stockholm")
        df = prepare_df(input_data, timezone_name)

        # Rev O1: Zero out PV if no solar panels
        if not has_solar:
            logger.info("No solar panels - zeroing PV forecasts")
            df["pv_forecast_kwh"] = 0.0
            if "adjusted_pv_kwh" in df.columns:
                df["adjusted_pv_kwh"] = 0.0

        # Determine 'now' slot
        tz = pytz.timezone(timezone_name)
        if now_override:
            if now_override.tzinfo is None:
                now_slot = pd.Timestamp(now_override, tz="UTC").tz_convert(tz).ceil("15min")
            else:
                now_slot = pd.Timestamp(now_override).tz_convert(tz).ceil("15min")
        else:
            now_slot = pd.Timestamp.now(tz=tz).floor("15min")
        now_dt: datetime = now_slot.to_pydatetime()

        # Per-device mid-block detection (task 3.1)
        # force_water_by_heater: heater_id → set of timestamps to force ON
        water_heaters_cfg: list[dict[str, Any]] = active_config.get("water_heaters", [])
        enabled_heater_ids: list[str] = [
            str(wh.get("id", ""))
            for wh in water_heaters_cfg
            if wh.get("enabled", True) and wh.get("id")
        ]
        force_water_by_heater: dict[str, set[pd.Timestamp]] = {d: set() for d in enabled_heater_ids}

        if previous_schedule and enabled_heater_ids:
            try:
                now_iso = now_slot.isoformat()
                current_idx = -1
                i: int = 0
                s: dict[str, Any]
                for i, s in enumerate(previous_schedule):
                    if s["start_time"].startswith(now_iso[:16]):  # type: ignore[union-attr]
                        current_idx = i
                        break

                if current_idx >= 0:
                    curr: dict[str, Any] = previous_schedule[current_idx]
                    curr_water_heaters: dict[str, Any] = curr.get("water_heaters", {})

                    for heater_id in enabled_heater_ids:
                        # Check if this specific heater is currently active
                        heater_data: dict[str, Any] = curr_water_heaters.get(heater_id, {})
                        currently_heating = float(heater_data.get("heating_kw", 0.0)) > 0

                        if currently_heating:
                            logger.info(
                                "Mid-block lock: heater %s is active - locking remaining slots.",
                                heater_id,
                            )
                            for j in range(current_idx, len(previous_schedule)):
                                slot_s = previous_schedule[j]
                                slot_water_heaters: dict[str, Any] = slot_s.get("water_heaters", {})
                                slot_heater: dict[str, Any] = slot_water_heaters.get(heater_id, {})
                                slot_heating = float(slot_heater.get("heating_kw", 0.0)) > 0
                                if slot_heating:
                                    ts = pd.Timestamp(slot_s["start_time"]).astimezone(tz)  # type: ignore[arg-type,index]
                                    force_water_by_heater[heater_id].add(ts)
                                else:
                                    break
            except Exception as e:
                logger.warning("Failed to determine per-device forced water slots: %s", e)

        # 3. Strategy (S-Index & Safety Margins)
        s_index_debug: dict[str, Any] = {}
        effective_load_margin = 1.0
        target_soc_kwh = 0.0
        target_soc_pct = 0.0
        s_index_cfg: dict[str, Any] = {}

        if mode == "full":
            # Calculate S-Index / Load Inflation
            # Note: Legacy uses static/base factor for load inflation (D1 safety)
            # and dynamic risk factor for target SoC (D2 strategy)

            s_index_cfg = active_config.get("s_index", {}) or {}
            base_factor = float(s_index_cfg.get("base_factor", 1.05))

            # Apply learned base factor
            if "s_index_base_factor" in learning_overlays:
                base_factor = float(learning_overlays["s_index_base_factor"])
                # Update cfg copy so functions see the learned value
                s_index_cfg = s_index_cfg.copy()
                s_index_cfg["base_factor"] = base_factor

            # Mode Check: Probabilistic vs Dynamic
            s_debug: dict[str, Any] = {}
            if s_index_cfg.get("mode") == "probabilistic":
                factor, s_debug = calculate_probabilistic_s_index(
                    df,
                    s_index_cfg,
                    float(s_index_cfg.get("max_factor", 1.5)),
                    timezone_name,
                    daily_probabilistic=input_data.get("daily_probabilistic"),
                )
                if factor is not None:
                    effective_load_margin = factor
                else:
                    logger.warning("Probabilistic S-Index failed (using base_factor): %s", s_debug)
                    effective_load_margin = base_factor

                s_index_debug.update(s_debug or {})
            else:
                # Legacy Dynamic Calculation
                factor, s_debug, _ = await calculate_dynamic_s_index(
                    df,
                    s_index_cfg,
                    float(s_index_cfg.get("max_factor", 1.5)),
                    timezone_name,
                    fetch_temperature_fn=lambda days, t: fetch_temperature_forecast(
                        days, t, active_config
                    ),
                )
                effective_load_margin = factor if factor is not None else base_factor

                s_index_debug.update(s_debug or {})

            # Rev K23 Phase 3: Physical Deficit Logic
            # Replaces legacy Risk Factor + Dynamic Target SoC logic
            # Temporal Safety Floor: Build full forecast DataFrame beyond price horizon
            from planner.inputs.data_prep import build_forecast_dataframe

            price_horizon_end = df.index[-1] if len(df) > 0 else None
            full_forecast_data = cast(
                "list[dict[str, Any]]",
                input_data.get("extended_forecast_data") or input_data.get("forecast_data") or [],
            )
            full_forecast_df = build_forecast_dataframe(full_forecast_data, timezone_name)

            soc_debug: dict[str, Any] = {}

            # Module 3: fetch price forecast data for the Layer 2 safety floor addon.
            upcoming_spots: dict[int, float] | None = None
            trailing_spot: float | None = None
            if active_config.get("price_forecast", {}).get("enabled", False):
                _db_path = active_config.get("learning", {}).get(
                    "sqlite_path", "data/planner_learning.db"
                )
                upcoming_spots, trailing_spot = await fetch_price_floor_inputs(
                    _db_path, timezone_name
                )

            target_soc_kwh, soc_debug = calculate_safety_floor(
                df,
                active_config.get("battery", {}),
                s_index_cfg,
                timezone_name,
                fetch_temperature_fn=lambda days, t: fetch_temperature_forecast(
                    days, t, active_config
                ),
                full_forecast_df=full_forecast_df,
                price_horizon_end=price_horizon_end,
                upcoming_daily_avg_spots=upcoming_spots,
                trailing_avg_spot=trailing_spot,
            )

            # Derive percentage for UI/Legacy compatibility
            battery_cap = float(active_config.get("battery", {}).get("capacity_kwh", 13.5) or 13.5)
            target_soc_pct = (target_soc_kwh / battery_cap) * 100.0 if battery_cap > 0 else 0.0
            raw_factor: float | None = None

            logger.info(
                "S-Index: Mode=temporal_deficit, TemporalDeficit=%.2f kWh, Floor=%.2f kWh (%.2f%%), Risk=%d",
                soc_debug.get("temporal_deficit_kwh", 0.0),
                target_soc_kwh,
                target_soc_pct,
                s_index_cfg.get("risk_appetite", 3),
            )

            # Extract raw factor from s_debug (handle both naming conventions)
            raw_factor = s_index_debug.get("raw_factor", s_index_debug.get("factor_unclamped"))  # type: ignore[assignment]

            s_index_debug = {
                "mode": "physical_deficit",
                "base_factor": base_factor,
                "effective_load_margin": effective_load_margin,
                "raw_factor": raw_factor,  # Kept for visibility of D1 margin
                "avg_deficit": s_index_debug.get("avg_deficit"),
                "temp_adjustment": s_index_debug.get("temp_adjustment"),
                "mean_temperature_c": s_index_debug.get("mean_temperature_c"),
                "safety_floor": soc_debug,
            }

            # Apply Safety Margins (PV confidence, Load inflation, Overlays)
            df = apply_safety_margins(df, active_config, learning_overlays, effective_load_margin)
        else:
            # Baseline mode: No safety margins, raw forecasts
            df["adjusted_pv_kwh"] = df["pv_forecast_kwh"]
            df["adjusted_load_kwh"] = df["load_forecast_kwh"]

        # 4. Per-device today's energy tracking (task 3.2)
        initial_state = input_data.get("initial_state", {})
        # Look for per-device states first, fall back to distributing aggregate
        ha_water_states_raw: list[dict[str, Any]] = initial_state.get("water_heater_states", [])
        ha_water_today_total = float(initial_state.get("water_heated_today_kwh", 0.0))

        # Build per-device heated_today lookup from HA states or aggregate fallback
        water_heated_today_by_id: dict[str, float] = {}
        if ha_water_states_raw:
            for wh_state in ha_water_states_raw:
                hid = str(wh_state.get("id", ""))
                if hid:
                    water_heated_today_by_id[hid] = float(wh_state.get("heated_today_kwh", 0.0))
        elif ha_water_today_total > 0 and len(enabled_heater_ids) == 1:
            # Single heater: assign total to it
            water_heated_today_by_id[enabled_heater_ids[0]] = ha_water_today_total

        # 5. Run Solver (Kepler)
        # CRITICAL: Only pass FUTURE slots to Kepler, starting from NOW with CURRENT real SoC
        # This ensures replanning during the day uses actual battery state, not midnight projection

        # Get current real SoC from Home Assistant
        initial_soc_kwh = float(
            initial_state.get("battery_kwh", initial_state.get("battery_soc_kwh", 0.0))
        )
        if initial_soc_kwh == 0.0 and "battery_soc_percent" in initial_state:
            cap = float(active_config.get("battery", {}).get("capacity_kwh", 0.0))
            initial_soc_kwh = (float(initial_state["battery_soc_percent"]) / 100.0) * cap

        logger.info("Pipeline initial_soc_kwh: %.3f (real SoC from HA)", initial_soc_kwh)

        # Filter to FUTURE slots only (>= now_slot)
        future_df = df[df.index >= now_slot].copy()
        if future_df.empty:
            logger.warning("No future slots available for Kepler! Using full DataFrame.")
            future_df = df.copy()
        else:
            logger.info(
                "Kepler: Planning %d future slots starting from %s", len(future_df), now_slot
            )

        # Map per-device forced timestamps to Kepler slot indices (task 3.1)
        force_on_slots_by_heater: dict[str, list[int]] = {}
        for heater_id, forced_ts in force_water_by_heater.items():
            if not forced_ts:
                continue
            indices: list[int] = []
            for idx, (ts, _) in enumerate(future_df.iterrows()):
                if ts in forced_ts:
                    indices.append(idx)
            if indices:
                force_on_slots_by_heater[heater_id] = indices
                logger.info(
                    "Mid-block lock: heater %s forcing %d slots ON",
                    heater_id,
                    len(indices),
                )

        # Build per-device water heater states for the adapter (task 3.3)
        water_heater_states: list[dict[str, Any]] = []
        for heater_id in enabled_heater_ids:
            water_heater_states.append(
                {
                    "id": heater_id,
                    "heated_today_kwh": water_heated_today_by_id.get(heater_id, 0.0),
                    "force_on_slots": force_on_slots_by_heater.get(heater_id),
                }
            )

        # Get max DC input for PV clipping
        max_dc_input_kw = system_cfg.get("inverter", {}).get("max_dc_input_kw")
        if max_dc_input_kw is not None:
            max_dc_input_kw = float(max_dc_input_kw)

        kepler_input = planner_to_kepler_input(future_df, initial_soc_kwh, max_dc_input_kw)
        kepler_config = config_to_kepler_config(
            active_config,
            overrides,
            kepler_input.slots,
            water_heater_states=water_heater_states,  # task 3.3
        )

        # Pre-calculate excess PV slot flags from raw forecasts (task 3.1)
        if len(kepler_config.excess_pv_priority) > 0 and len(kepler_input.slots) > 0:
            excess_pv_flags = _calculate_excess_pv_flags(
                kepler_input.slots,
                kepler_config.water_heaters,
                kepler_config.ev_chargers,
                future_df,
            )
            kepler_config.excess_pv_slots = excess_pv_flags
            logger.info(
                "Excess PV: %d/%d slots have excess PV (sinks=%s)",
                sum(excess_pv_flags),
                len(excess_pv_flags),
                [e.type for e in kepler_config.excess_pv_priority],
            )

        # Rev O1: Disable water heating in Kepler if no water heater (task 3.4)
        if not has_water_heater:
            logger.info("No water heater - disabling water heating optimization")
            kepler_config.water_heaters = []

        # Rev O1: Constrain battery if no battery system
        if not has_battery:
            logger.info("No battery - disabling battery optimization (charge/discharge disabled)")
            kepler_config.max_charge_power_kw = 0.0
            kepler_config.max_discharge_power_kw = 0.0

        # Per-device EV state: build EVChargerInput list for Kepler
        has_ev_charger = system_cfg.get("has_ev_charger", False)
        ev_charger_states_with_goal: list[dict[str, Any]] = []
        ev_chargers_cfg: list[dict[str, Any]] = []
        if has_ev_charger:
            ev_charger_states_raw: list[dict[str, Any]] = initial_state.get("ev_charger_states", [])
            ev_chargers_cfg_raw: list[dict[str, Any]] = active_config.get("ev_chargers", [])
            timezone_name = active_config.get("timezone", "Europe/Stockholm")
            tz = pytz.timezone(timezone_name)
            sqlite_path: str = active_config.get("learning", {}).get(
                "sqlite_path", "data/planner_learning.db"
            )

            from backend.core.ev_state import read_ev_state

            ev_state_data = read_ev_state()
            ev_chargers_cfg = merge_ev_goals_from_state(ev_chargers_cfg_raw, ev_state_data)
            enabled_charger_count = sum(1 for c in ev_chargers_cfg if c.get("enabled", True))

            # Calculate per-device goals and attach to state dicts
            upcoming_spots: dict[int, float] | None = None
            needs_price_forecast = False

            for ev_cfg_item in ev_chargers_cfg:
                if not ev_cfg_item.get("enabled", True):
                    continue
                charger_id = ev_cfg_item.get("id", "")
                default_state: dict[str, Any] = {}
                # Find matching HA state
                ha_state = next(
                    (s for s in ev_charger_states_raw if s.get("id") == charger_id),
                    default_state,
                )
                plugged_in = bool(ha_state.get("plugged_in", False))
                deadline: datetime | None = None
                required_kwh: float | None = None
                keep_on_after_target = bool(ev_cfg_item.get("keep_on_after_target", False))

                if plugged_in:
                    deadline = resolve_next_ready_by(
                        ev_cfg_item,
                        now_dt,
                        tz,
                    )
                    if deadline is not None:
                        required_kwh = _calculate_required_kwh(
                            ev_cfg_item,
                            ha_state,
                            sqlite_path,
                            tz,
                            single_enabled_charger=(enabled_charger_count == 1),
                        )
                        # Multi-day spreading only when deadline is far and a
                        # forecast may be available.
                        if (deadline - now_dt).total_seconds() > 86400:
                            needs_price_forecast = True
                        logger.info(
                            "EV %s: SoC=%.1f%%, Plugged=%s, Target=%d%%, "
                            "Required=%.2f kWh, ReadyBy=%s, Deadline=%s",
                            charger_id,
                            ha_state.get("soc_percent") or 0.0,
                            plugged_in,
                            ev_cfg_item.get("target_soc_percent"),
                            required_kwh or 0.0,
                            ev_cfg_item.get("ready_by"),
                            deadline.strftime("%Y-%m-%d %H:%M"),
                        )
                    else:
                        logger.info(
                            "EV %s: SoC=%.1f%%, Plugged=%s, no active deadline",
                            charger_id,
                            ha_state.get("soc_percent") or 0.0,
                            plugged_in,
                        )

                ev_charger_states_with_goal.append(
                    {
                        "id": charger_id,
                        "soc_percent": ha_state.get("soc_percent"),
                        "plugged_in": plugged_in,
                        "deadline": deadline,
                        "required_kwh": required_kwh,
                        "keep_on_after_target": keep_on_after_target,
                        "daily_quota_kwh": None,
                        "quota_schedule": None,
                    }
                )

            # Fetch 7-day forecast once if any plugged charger has a far deadline.
            if needs_price_forecast:
                try:
                    upcoming_spots, _ = await fetch_price_floor_inputs(sqlite_path, timezone_name)
                except Exception as exc:
                    logger.warning("Could not fetch price-floor inputs for EV spreading: %s", exc)
                    upcoming_spots = {}

                for state in ev_charger_states_with_goal:
                    deadline = cast("datetime | None", state.get("deadline"))
                    required_kwh = cast("float | None", state.get("required_kwh"))
                    if deadline is None or required_kwh is None:
                        continue
                    if (deadline - now_dt).total_seconds() <= 86400:
                        continue
                    ev_cfg_item: dict[str, Any] = next(
                        (c for c in ev_chargers_cfg if c.get("id") == state["id"]),
                        cast("dict[str, Any]", {}),
                    )
                    today_quota, quota_schedule = _compute_daily_ev_quota(
                        ev_cfg_item,
                        deadline,
                        required_kwh,
                        upcoming_spots or {},
                        now_dt,
                        tz,
                    )
                    state["daily_quota_kwh"] = today_quota
                    state["quota_schedule"] = quota_schedule
                    if today_quota is not None:
                        logger.info(
                            "EV %s: multi-day quota today=%.2f kWh, schedule=%s",
                            state["id"],
                            today_quota,
                            {str(k): round(v, 2) for k, v in (quota_schedule or {}).items()},
                        )

            # Rebuild kepler_config with per-device EV charger inputs
            from planner.solver.adapter import build_ev_charger_inputs

            kepler_config.ev_chargers = build_ev_charger_inputs(
                ev_chargers_cfg, ev_charger_states_with_goal
            )

            # Persist transient EV goal/progress state for the read-only API
            # (price-forecasting-module-4 §5.2). Best-effort; never fatal.
            try:
                _persist_ev_multi_day_state(
                    ev_charger_states_with_goal,
                    ev_chargers_cfg,
                    sqlite_path,
                    tz,
                    now_dt,
                )
            except Exception as exc:
                logger.warning("EV multi-day state persistence failed: %s", exc)

            # Rev K19: Vacation Mode Anti-Legionella
        vacation_cfg = water_cfg.get("vacation_mode", {})
        vacation_enabled = vacation_cfg.get("enabled", False)
        schedule_anti_legionella = False
        sqlite_path: str = ""

        # HA entity can override config when ON
        ha_vacation = initial_state.get("vacation_mode", False)
        if ha_vacation:
            vacation_enabled = True

        if vacation_enabled:
            logger.info("Vacation mode enabled - disabling comfort-based water heating")
            # Disable water heating (clear the per-device list)
            kepler_config.water_heaters = []
            kepler_config.water_heating_max_gap_hours = 0.0

            # Check if anti-legionella cycle is due
            sqlite_path = active_config.get("learning", {}).get(
                "sqlite_path", "data/planner_learning.db"
            )
            last_al = load_last_anti_legionella(sqlite_path)

            # Smart detection: If water was already heated today (≥2 kWh), treat as done
            ha_water_today_total = (
                sum(water_heated_today_by_id.values())
                if water_heated_today_by_id
                else ha_water_today_total
            )
            if last_al is None and ha_water_today_total >= 2.0:
                logger.info(
                    "Vacation mode: No prior anti-legionella record, but %.1f kWh already heated today. "
                    "Setting last_anti_legionella_at to today.",
                    ha_water_today_total,
                )
                save_last_anti_legionella(sqlite_path, now_slot.to_pydatetime())
                last_al = now_slot.to_pydatetime()

            days_since = (
                (now_slot.to_pydatetime().replace(tzinfo=None) - last_al.replace(tzinfo=None)).days
                if last_al
                else 999
            )
            interval_days = int(vacation_cfg.get("anti_legionella_interval_days", 7))

            if days_since >= (interval_days - 1) and now_slot.hour >= 14:
                duration_hours = float(vacation_cfg.get("anti_legionella_duration_hours", 3.0))
                # Rebuild per-device water heaters for anti-legionella
                # Each heater runs for duration_hours, min_kwh = power_kw * duration_hours
                from planner.solver.adapter import build_water_heater_inputs

                al_heaters = build_water_heater_inputs(
                    water_heaters_cfg, active_config.get("water_heating", {}), water_heater_states
                )
                for h in al_heaters:
                    h.min_kwh_per_day = h.power_kw * duration_hours
                kepler_config.water_heaters = al_heaters
                al_kwh_total = sum(h.min_kwh_per_day for h in al_heaters)
                schedule_anti_legionella = True
                logger.info(
                    "Anti-legionella due: %d days since last (interval=%d). Scheduling %.1f kWh across %d heaters.",
                    days_since,
                    interval_days,
                    al_kwh_total,
                    len(al_heaters),
                )
            else:
                logger.debug(
                    "Anti-legionella not due: %d days since last, hour=%d",
                    days_since,
                    now_slot.hour,
                )

        logger.info(
            "Kepler input initial_soc_kwh: %.3f, water_heated_today: %.2f kWh",
            kepler_input.initial_soc_kwh,
            ha_water_today_total,
        )

        # Target SoC is applied via soft constraint in Kepler solver:
        # - min_soc violation: 1000 SEK/kWh (HARD - don't violate!)
        # - target violation: derived from risk_appetite (SOFT - economics can override)
        # Safety = high penalty (harder to violate), Gambler = low penalty (easier to trade off)
        if mode == "full" and target_soc_kwh > 0:
            kepler_config.target_soc_kwh = target_soc_kwh

            # Target penalty derived from risk_appetite
            RISK_PENALTY_MAP = {
                1: 200.0,  # Safety: Strong incentive to hit target
                2: 200.0,
                3: 200.0,
                4: 200.0,
                5: 200.0,
            }
            risk_appetite = int(s_index_cfg.get("risk_appetite", 3))
            kepler_config.target_soc_penalty_sek = RISK_PENALTY_MAP.get(risk_appetite, 8.0)

        run_preflight(input_data, active_config)

        solver = KeplerSolver()
        result = await asyncio.to_thread(solver.solve, kepler_input, kepler_config)

        if has_ev_charger and result.slots:
            try:
                _apply_keep_on_after_target(
                    result, ev_charger_states_with_goal, ev_chargers_cfg, now_dt
                )
            except Exception as exc:
                logger.warning("keep_on_after_target injection failed: %s", exc)

            _warn_on_zero_scheduled_active_goals(
                result, ev_charger_states_with_goal, ev_chargers_cfg
            )

        if result.slots:
            logger.info(
                "Kepler result: %d slots, first soc_kwh=%.3f",
                len(result.slots),
                result.slots[0].soc_kwh,
            )

            # Rev K19: Save anti-legionella timestamp if scheduled
            if schedule_anti_legionella:
                # Check if water heating was actually planned
                water_slots = [s for s in result.slots if s.water_heat_kw > 0]
                if water_slots:
                    save_last_anti_legionella(sqlite_path, now_slot.to_pydatetime())
                    logger.info("Anti-legionella cycle scheduled, timestamp saved.")

        # Convert result back to DataFrame
        capacity = kepler_config.capacity_kwh
        result_df = kepler_result_to_dataframe(result, capacity, initial_soc_kwh)

        logger.info(
            "result_df first projected_soc_kwh: %.3f",
            result_df.iloc[0]["projected_soc_kwh"] if len(result_df) > 0 else 0.0,
        )

        # Preserve water_heating_kw before merge (Kepler doesn't know about water heating)
        water_heating_series = (
            future_df["water_heating_kw"].copy()
            if "water_heating_kw" in future_df.columns
            else None
        )

        # Merge result back into future_df (not full df!)
        # Kepler only planned future slots, so result_df matches future_df indices
        final_df = future_df.join(result_df, rsuffix="_kepler")

        if len(result_df) != len(future_df):
            logger.error(
                "Result merge length mismatch: result_df=%d, future_df=%d — "
                "possible duplicate timestamps in price input",
                len(result_df),
                len(future_df),
            )

        # Copy ALL columns from result_df to final_df (overwrite existing, add new)
        # Use index-aligned assignment (not .values) to avoid ValueError on length mismatch
        for col in result_df.columns:
            final_df[col] = result_df[col]

        # Restore water_heating_kw (it was set in schedule_water_heating but overwritten above)
        if water_heating_series is not None:
            final_df["water_heating_kw"] = water_heating_series

        # 6. Manual Plan
        final_df = apply_manual_plan(final_df, active_config)

        # 7. Apply dynamic soc_target_percent based on actions
        # This sets per-slot targets: Charge blocks → projected end SoC,
        # Export blocks → projected end SoC, Discharge → min_soc, Hold → entry SoC
        final_df = apply_soc_target_percent(final_df, active_config, now_slot)

        # 7. Output & Observability
        # Safety Check: Do not save empty/garbage plan
        if mode == "full" and (final_df.empty or "battery_charge_kw" not in final_df.columns):
            logger.error(
                "Planner generated invalid schedule (empty or missing columns). Aborting save to prevent data loss."
            )
            raise PlannerError(
                code=PlannerErrorCode.INVALID_SCHEDULE,
                details={
                    "solver_status": result.status_msg if result else "unknown",
                    "initial_soc_kwh": initial_soc_kwh,
                    "max_soc_kwh": kepler_config.capacity_kwh
                    * kepler_config.max_soc_percent
                    / 100.0,
                    "capacity_kwh": kepler_config.capacity_kwh,
                },
            )

        if save_to_file:
            # Prepare window responsibilities (placeholder, Kepler doesn't return windows yet)
            # We can infer them or leave empty.
            window_responsibilities: list[dict[str, Any]] = []

            # Planner State for debug
            planner_state_debug = {
                "cheap_price_threshold": 0.0,  # Kepler doesn't expose this
                "price_smoothing_tolerance": 0.0,
                "cheap_slot_count": 0,
                "non_cheap_slot_count": 0,
            }

            forecast_meta = {"pv_forecast_days": 2, "weather_forecast_days": 2}  # Estimate

            # Add soc_target to s_index_debug for output
            if mode == "full":
                s_index_debug["soc_target_kwh"] = target_soc_kwh
                s_index_debug["soc_target_percent"] = target_soc_pct

            await save_schedule_to_json(
                final_df,
                active_config,
                now_slot,
                forecast_meta,
                s_index_debug,
                window_responsibilities,
                planner_state_debug,
            )

            # Rev UI5: Always store plan to slot_plans for performance tracking
            try:
                tz = pytz.timezone(timezone_name)
                sqlite_path = active_config.get("learning", {}).get(
                    "sqlite_path", "data/planner_learning.db"
                )
                store = LearningStore(sqlite_path, tz)
                # Reset index so start_time becomes a column (store_plan expects it)
                plan_df = final_df.reset_index()
                await store.store_plan(plan_df)
                logger.debug("Stored plan to slot_plans for performance tracking")
            except Exception as store_err:
                logger.warning("Failed to store plan to slot_plans: %s", store_err)

            # Note: Cache invalidation and WebSocket emit moved to planner_service.py (Rev ARC8)

        return final_df


async def generate_schedule(
    input_data: dict[str, Any],
    config: dict[str, Any] | None = None,
    mode: str = "full",
    save_to_file: bool = True,
    ev_plug_override_charger_id: str | None = None,
) -> pd.DataFrame:
    """
    Convenience function to generate a schedule.

    Args:
        input_data: Dictionary with price_data, forecast_data, initial_state
        config: Optional config dict (loads from config.yaml if not provided)
        mode: "full" or "baseline"
        save_to_file: Whether to save schedule.json

    Returns:
        DataFrame with the complete schedule
    """
    if config is None:
        import yaml

        with Path("config.yaml").open() as f:
            config = yaml.safe_load(f)

    config_dict: dict[str, Any] = config or {}
    pipeline = PlannerPipeline(config_dict)
    return await pipeline.generate_schedule(
        input_data,
        mode=mode,
        save_to_file=save_to_file,
        ev_plug_override_charger_id=ev_plug_override_charger_id,
    )
