import asyncio
import hashlib
import json
import logging
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends

from backend.api.deps import get_learning_store
from backend.baseline import BaselineBattery, BaselineSlot, simulate_self_use_with_end_state
from backend.battery_comparison import (
    METHOD_VERSION,
    CalibrationResult,
    ComparisonBattery,
    RecordedObservation,
    build_comparison,
    fit_calibration,
)
from backend.core.secrets import load_yaml
from backend.learning.store import LearningStore

logger = logging.getLogger("darkstar.api.energy")

_BATTERY_FIT_CACHE: dict[str, tuple[float, CalibrationResult]] = {}
_BATTERY_FIT_CACHE_TTL_SECONDS = 900
_BATTERY_FIT_CACHE_LIMIT = 16


def _cached_fit_key(
    store: LearningStore,
    battery: BaselineBattery,
    config: dict[str, Any],
    latest: datetime,
    end: datetime,
) -> str:
    try:
        db_stat = Path(store.db_path).stat()
        database_identity: tuple[int, int, int, int] | None = (
            db_stat.st_dev,
            db_stat.st_ino,
            db_stat.st_size,
            db_stat.st_mtime_ns,
        )
    except OSError:
        database_identity = None
    relevant = {
        "db": str(store.db_path),
        "db_identity": database_identity,
        "battery": battery.__dict__,
        "sensors": config.get("input_sensors", {}),
        "meter": config.get("meter", config.get("system", {}).get("meter")),
        "method": METHOD_VERSION,
        "latest": latest.astimezone(UTC).isoformat(),
        "end": end.astimezone(UTC).isoformat(),
    }
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, default=str).encode()).hexdigest()


async def _calibrated_fit(
    store: LearningStore,
    battery: BaselineBattery,
    config: dict[str, Any],
    observations: list[RecordedObservation],
    end: datetime,
    latest: datetime,
) -> CalibrationResult:
    key = _cached_fit_key(store, battery, config, latest, end)
    now = time.monotonic()
    cached = _BATTERY_FIT_CACHE.get(key)
    if cached is not None and now - cached[0] < _BATTERY_FIT_CACHE_TTL_SECONDS:
        return cached[1]
    result = await asyncio.to_thread(fit_calibration, observations, battery.capacity_kwh, end)
    _BATTERY_FIT_CACHE[key] = (time.monotonic(), result)
    while len(_BATTERY_FIT_CACHE) > _BATTERY_FIT_CACHE_LIMIT:
        oldest = min(_BATTERY_FIT_CACHE, key=lambda item: _BATTERY_FIT_CACHE[item][0])
        del _BATTERY_FIT_CACHE[oldest]
    return result


router = APIRouter(prefix="/api", tags=["energy"])


@router.get(
    "/performance/data",
    summary="Get Performance Data",
    description="Get performance metrics for the Aurora card.",
)
async def get_performance_data(days: int = 7) -> dict[str, Any]:
    """Get performance metrics for Aurora card."""
    try:
        from backend.learning import get_learning_engine

        engine = get_learning_engine()
        if hasattr(engine, "get_performance_series"):
            # get_performance_series is now async
            data = await engine.get_performance_series(days_back=days)
            return cast("dict[str, Any]", data)
        else:
            return {
                "soc_series": [],
                "cost_series": [],
                "mae_pv_aurora": None,
                "mae_pv_baseline": None,
                "mae_load_aurora": None,
                "mae_load_baseline": None,
            }
    except Exception as e:
        return {
            "soc_series": [],
            "cost_series": [],
            "mae_pv_aurora": None,
            "mae_pv_baseline": None,
            "mae_load_aurora": None,
            "mae_load_baseline": None,
            "error": str(e),
        }


BASE_LOAD_WINDOW_SLOTS = 96
BASE_LOAD_MIN_SLOTS = 87


async def _base_load_avg_daily_kwh(store: LearningStore, now: datetime) -> float | None:
    """Base-load total of the last 96 completed 15-minute slots, scaled to 96 slots.

    Returns None when fewer than 87 of those slots have a recorded ``load_kwh``.
    """
    from sqlalchemy import func, select

    from backend.learning.models import SlotObservation

    # Window arithmetic in UTC so a DST change can't widen or shrink it; bounds are
    # then rendered in the store's timezone to match the stored slot_start strings.
    now_utc = now.astimezone(UTC)
    current_slot_start = now_utc.replace(
        minute=now_utc.minute - now_utc.minute % 15, second=0, microsecond=0
    )
    window_start = current_slot_start - timedelta(minutes=15 * BASE_LOAD_WINDOW_SLOTS)
    start_iso = window_start.astimezone(store.timezone).isoformat()
    end_iso = current_slot_start.astimezone(store.timezone).isoformat()

    async with store.AsyncSession() as session:
        stmt = select(
            func.sum(SlotObservation.load_kwh),
            func.count(SlotObservation.load_kwh),
        ).where(SlotObservation.slot_start >= start_iso, SlotObservation.slot_start < end_iso)
        row = (await session.execute(stmt)).fetchone()

    if not row:
        return None
    total = float(row[0] or 0.0)
    count = int(row[1] or 0)
    if count < BASE_LOAD_MIN_SLOTS:
        return None
    return round(total * BASE_LOAD_WINDOW_SLOTS / count, 2)


@router.get(
    "/energy/today",
    summary="Get Today's Energy",
    description="Get today's energy summary from database (SlotObservation table).",
)
async def get_energy_today(
    store: LearningStore = Depends(get_learning_store),
) -> dict[str, float | None]:
    """Get today's energy summary from database aggregation."""
    # Delegate to energy/range with period="today" to avoid duplicate query logic
    range_data = await get_energy_range(period="today", store=store)

    # Extract values from range response (using unified keys)
    grid_imp_kwh = range_data.get("grid_import_kwh", 0.0)
    grid_exp_kwh = range_data.get("grid_export_kwh", 0.0)
    pv_kwh = range_data.get("pv_production_kwh", 0.0)
    load_kwh = range_data.get("load_consumption_kwh", 0.0)
    batt_chg_kwh = range_data.get("battery_charge_kwh", 0.0)
    batt_dis_kwh = range_data.get("battery_discharge_kwh", 0.0)
    ev_kwh = range_data.get("ev_charging_kwh", 0.0)
    ev_grid_kwh = range_data.get("ev_grid_kwh", 0.0)
    ev_solar_kwh = range_data.get("ev_solar_kwh", 0.0)
    ev_cost_sek = range_data.get("ev_cost_sek", 0.0)
    ev_solar_share = range_data.get("ev_solar_share")
    water_kwh = range_data.get("water_heating_kwh", 0.0)
    net_cost = range_data.get("net_cost_sek", 0.0)
    battery_wear_cost = range_data.get("battery_wear_cost_sek", 0.0)
    net_cost_incl_wear = range_data.get("net_cost_incl_wear_sek", 0.0)

    # Calculate battery cycles
    config = load_yaml("config.yaml")
    base_load_avg: float | None = None
    try:
        base_load_avg = await _base_load_avg_daily_kwh(store, datetime.now(UTC))
    except Exception as e:
        logger.warning("Failed to compute base-load daily average: %s", e)
    battery_cycles = 0.0
    try:
        cap = float(config.get("battery", {}).get("capacity_kwh", 0.0))
        if cap > 0:
            battery_cycles = batt_dis_kwh / cap
    except Exception:
        pass

    # Return unified response with both legacy aliases and new keys
    return {
        # New unified keys (match energy/range)
        "pv_production_kwh": round(pv_kwh, 2),
        "load_consumption_kwh": round(load_kwh, 2),
        "grid_import_kwh": round(grid_imp_kwh, 2),
        "grid_export_kwh": round(grid_exp_kwh, 2),
        "battery_charge_kwh": round(batt_chg_kwh, 2),
        "battery_discharge_kwh": round(batt_dis_kwh, 2),
        "ev_charging_kwh": round(ev_kwh, 2),
        "ev_grid_kwh": round(ev_grid_kwh, 2),
        "ev_solar_kwh": round(ev_solar_kwh, 2),
        "ev_cost_sek": round(ev_cost_sek, 2),
        "ev_solar_share": ev_solar_share,
        "water_heating_kwh": round(water_kwh, 2),
        "net_cost_sek": round(net_cost, 2),
        "battery_wear_cost_sek": round(battery_wear_cost, 2),
        "net_cost_incl_wear_sek": round(net_cost_incl_wear, 2),
        "battery_cycles": round(battery_cycles, 2),
        "base_load_avg_daily_kwh": base_load_avg,
        # Legacy aliases (for backwards compatibility during transition)
        "solar": round(pv_kwh, 2),
        "consumption": round(load_kwh, 2),
        "grid_import": round(grid_imp_kwh, 2),
        "grid_export": round(grid_exp_kwh, 2),
        "net_cost_kr": round(net_cost, 2),
    }


def _resolve_period(
    period: str, start_date: str | None, end_date: str | None, today_local: date
) -> tuple[date, date]:
    """Inclusive local date range for a period name (today, yesterday, week, month, custom)."""
    if period == "custom" and start_date and end_date:
        try:
            custom_start = datetime.strptime(start_date, "%Y-%m-%d").date()
            custom_end = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError as e:
            raise ValueError("Invalid date format. Use YYYY-MM-DD") from e
        if custom_end < custom_start:
            raise ValueError("End date must be after start date")
        return custom_start, custom_end
    if period == "yesterday":
        yesterday = today_local - timedelta(days=1)
        return yesterday, yesterday
    if period == "week":
        return today_local - timedelta(days=6), today_local
    if period == "month":
        return today_local - timedelta(days=29), today_local
    return today_local, today_local


@router.get(
    "/energy/range",
    summary="Get Energy Range",
    description="Get energy range data (today, yesterday, week, month, custom) from database.",
)
async def get_energy_range(
    period: str = "today",
    start_date: str | None = None,
    end_date: str | None = None,
    store: LearningStore = Depends(get_learning_store),
) -> dict[str, Any]:
    """Get energy range data from database (SlotObservation table)."""
    import pytz
    from sqlalchemy import func, select

    from backend.learning.models import SlotObservation

    config = load_yaml("config.yaml")

    try:
        tz = pytz.timezone(config.get("timezone", "Europe/Stockholm"))
        now_local = datetime.now(tz)
        today_local = now_local.date()

        query_start, query_end = _resolve_period(period, start_date, end_date, today_local)

        # Optimize query: filter by string range to use index
        day_start = tz.localize(datetime(query_start.year, query_start.month, query_start.day))
        # End date is inclusive in the logic, so we want up to the end of that day.
        # Logic says: DATE(slot_start) <= end_date.
        # So we want < end_date + 1 day
        day_end_excl = tz.localize(
            datetime(query_end.year, query_end.month, query_end.day)
        ) + timedelta(days=1)

        start_iso = day_start.isoformat()
        end_iso = day_end_excl.isoformat()

        # EV source attribution per slot (ev-cost-attribution): solar is bounded
        # by the measured PV surplus after base load and water heating, grid is
        # the remainder, so grid + solar = EV energy and zero PV means zero solar.
        # Battery charging is not subtracted, so solar is an upper bound.
        # EV cost is capped at the slot's import so it stays a subset of
        # import_cost_sek.
        ev_slot = func.max(0, func.coalesce(SlotObservation.ev_charging_kwh, 0))
        pv_surplus_slot = func.max(
            0,
            func.coalesce(SlotObservation.pv_kwh, 0)
            - func.coalesce(SlotObservation.load_kwh, 0)
            - func.coalesce(SlotObservation.water_kwh, 0),
        )
        ev_solar_slot = func.min(ev_slot, pv_surplus_slot)
        ev_grid_slot = ev_slot - ev_solar_slot
        ev_cost_kwh_slot = func.min(
            ev_grid_slot, func.max(0, func.coalesce(SlotObservation.import_kwh, 0))
        )

        async with store.AsyncSession() as session:
            stmt = select(
                func.sum(func.coalesce(SlotObservation.import_kwh, 0)),
                func.sum(func.coalesce(SlotObservation.export_kwh, 0)),
                func.sum(func.coalesce(SlotObservation.batt_charge_kwh, 0)),
                func.sum(func.coalesce(SlotObservation.batt_discharge_kwh, 0)),
                func.sum(func.coalesce(SlotObservation.water_kwh, 0)),
                func.sum(func.coalesce(SlotObservation.pv_kwh, 0)),
                func.sum(func.coalesce(SlotObservation.load_kwh, 0)),
                func.sum(func.coalesce(SlotObservation.ev_charging_kwh, 0)),
                # Costs
                func.sum(
                    func.coalesce(SlotObservation.import_kwh, 0)
                    * func.coalesce(SlotObservation.import_price_sek_kwh, 0)
                ),
                func.sum(
                    func.coalesce(SlotObservation.export_kwh, 0)
                    * func.coalesce(SlotObservation.export_price_sek_kwh, 0)
                ),
                # Grid Charge Cost
                func.sum(
                    func.max(
                        0,
                        func.coalesce(SlotObservation.import_kwh, 0)
                        - func.coalesce(SlotObservation.load_kwh, 0),
                    )
                    * func.coalesce(SlotObservation.import_price_sek_kwh, 0)
                ),
                # Self Consumption Savings
                func.sum(
                    func.max(
                        0,
                        func.coalesce(SlotObservation.load_kwh, 0)
                        - func.coalesce(SlotObservation.import_kwh, 0),
                    )
                    * func.coalesce(SlotObservation.import_price_sek_kwh, 0)
                ),
                func.count(),
                # EV attribution (PV-surplus bound). ev_cost_sek is the EV's grid
                # import cost only, a subset of import_cost_sek; solar is not priced.
                func.sum(ev_grid_slot),
                func.sum(ev_solar_slot),
                func.sum(ev_cost_kwh_slot * func.coalesce(SlotObservation.import_price_sek_kwh, 0)),
            ).where(SlotObservation.slot_start >= start_iso, SlotObservation.slot_start < end_iso)
            result = await session.execute(stmt)
            row = result.fetchone()

        if not row:
            raise ValueError("No data returned")

        grid_imp_kwh = float(row[0] or 0.0)
        grid_exp_kwh = float(row[1] or 0.0)
        batt_chg_kwh = float(row[2] or 0.0)
        batt_dis_kwh = float(row[3] or 0.0)
        water_kwh = float(row[4] or 0.0)
        pv_kwh = float(row[5] or 0.0)
        load_kwh = float(row[6] or 0.0)
        ev_kwh = float(row[7] or 0.0)

        import_cost = float(row[8] or 0.0)
        export_rev = float(row[9] or 0.0)
        grid_charge_cost = float(row[10] or 0.0)
        self_cons_savings = float(row[11] or 0.0)
        slot_count = int(row[12] or 0)
        ev_grid_kwh = float(row[13] or 0.0)
        ev_solar_kwh = float(row[14] or 0.0)
        ev_cost_sek = float(row[15] or 0.0)
        ev_attributed_kwh = ev_grid_kwh + ev_solar_kwh
        ev_solar_share = (
            round(ev_solar_kwh / ev_attributed_kwh, 3) if ev_attributed_kwh > 0 else None
        )

        net_cost = import_cost - export_rev

        battery_cycle_cost_kwh = float(
            config.get("battery_economics", {}).get("battery_cycle_cost_kwh", 0.0)
        )
        battery_wear_cost_sek = (batt_chg_kwh + batt_dis_kwh) * battery_cycle_cost_kwh * 0.5
        net_cost_incl_wear_sek = net_cost + battery_wear_cost_sek

        # NOTE: No longer overlaying HA sensor values - using DB-only data
        # This ensures consistency with the recorder's isolation logic

        return {
            "period": period,
            "start_date": query_start.isoformat(),
            "end_date": query_end.isoformat(),
            "grid_import_kwh": round(grid_imp_kwh, 2),
            "grid_export_kwh": round(grid_exp_kwh, 2),
            "battery_charge_kwh": round(batt_chg_kwh, 2),
            "battery_discharge_kwh": round(batt_dis_kwh, 2),
            "water_heating_kwh": round(water_kwh, 2),
            "pv_production_kwh": round(pv_kwh, 2),
            "load_consumption_kwh": round(load_kwh, 2),
            "ev_charging_kwh": round(ev_kwh, 2),
            "ev_grid_kwh": round(ev_grid_kwh, 2),
            "ev_solar_kwh": round(ev_solar_kwh, 2),
            "ev_cost_sek": round(ev_cost_sek, 2),
            "ev_solar_share": ev_solar_share,
            "import_cost_sek": round(import_cost, 2),
            "export_revenue_sek": round(export_rev, 2),
            "grid_charge_cost_sek": round(grid_charge_cost, 2),
            "self_consumption_savings_sek": round(self_cons_savings, 2),
            "net_cost_sek": round(net_cost, 2),
            "battery_wear_cost_sek": round(battery_wear_cost_sek, 2),
            "net_cost_incl_wear_sek": round(net_cost_incl_wear_sek, 2),
            "slot_count": slot_count,
        }
    except Exception as e:
        # Fallback with zeros
        return {
            "period": period,
            "start_date": datetime.now().date().isoformat(),
            "end_date": datetime.now().date().isoformat(),
            "grid_import_kwh": 0.0,
            "grid_export_kwh": 0.0,
            "battery_charge_kwh": 0.0,
            "battery_discharge_kwh": 0.0,
            "water_heating_kwh": 0.0,
            "pv_production_kwh": 0.0,
            "load_consumption_kwh": 0.0,
            "ev_charging_kwh": 0.0,
            "ev_grid_kwh": 0.0,
            "ev_solar_kwh": 0.0,
            "ev_cost_sek": 0.0,
            "ev_solar_share": None,
            "import_cost_sek": 0.0,
            "export_revenue_sek": 0.0,
            "grid_charge_cost_sek": 0.0,
            "self_consumption_savings_sek": 0.0,
            "net_cost_sek": 0.0,
            "battery_wear_cost_sek": 0.0,
            "net_cost_incl_wear_sek": 0.0,
            "slot_count": 0,
            "error": str(e),
        }


def _baseline_battery(config: dict[str, Any]) -> BaselineBattery | None:
    """Battery for the without-Darkstar baseline, or None when there is no usable battery."""
    system_cfg = config.get("system", {})
    if not system_cfg.get("has_battery", True):
        return None
    cfg = system_cfg.get("battery", config.get("battery", {}))
    battery = BaselineBattery(
        capacity_kwh=float(cfg.get("capacity_kwh", 0.0)),
        min_soc_percent=float(cfg.get("min_soc_percent", 0.0)),
        max_soc_percent=float(cfg.get("max_soc_percent", 100.0)),
        max_charge_w=float(cfg.get("max_charge_w", 0.0)),
        max_discharge_w=float(cfg.get("max_discharge_w", 0.0)),
        charge_efficiency=float(cfg.get("charge_efficiency", 0.95)),
        discharge_efficiency=float(cfg.get("discharge_efficiency", 0.95)),
    )
    if (
        battery.capacity_kwh <= 0
        or battery.charge_efficiency <= 0
        or battery.discharge_efficiency <= 0
    ):
        return None
    return battery


@router.get(
    "/energy/cost-series",
    summary="Get Cost Series",
    description=(
        "Import cost, export revenue and running net cost over a period, bucketed by hour "
        "for a single day and by day for longer periods. Same pricing as /api/energy/range."
    ),
)
async def get_cost_series(
    period: str = "today",
    start_date: str | None = None,
    end_date: str | None = None,
    store: LearningStore = Depends(get_learning_store),
) -> dict[str, Any]:
    """Cost per bucket from SlotObservation, with the cumulative net cost."""
    import pytz
    from sqlalchemy import select

    from backend.learning.models import SlotObservation

    config = load_yaml("config.yaml")
    tz = pytz.timezone(config.get("timezone", "Europe/Stockholm"))
    now_local = datetime.now(tz)

    try:
        query_start, query_end = _resolve_period(period, start_date, end_date, now_local.date())
    except ValueError as e:
        return {"period": period, "bucket": "hour", "points": [], "error": str(e)}

    hourly = query_start == query_end
    day_start = tz.localize(datetime(query_start.year, query_start.month, query_start.day))
    next_day = query_end + timedelta(days=1)
    day_end_excl = tz.localize(datetime(next_day.year, next_day.month, next_day.day))

    battery = _baseline_battery(config)

    compare_end_local = min(day_end_excl, now_local)
    compare_end_utc = compare_end_local.astimezone(UTC)
    # Only complete 15-minute slots enter calibration and comparison. Keep the
    # legacy cash-flow series' started-slot coverage below unchanged.
    complete_boundary_utc = now_local.astimezone(UTC).replace(
        minute=now_local.astimezone(UTC).minute - now_local.astimezone(UTC).minute % 15,
        second=0,
        microsecond=0,
    )
    comparison_cutoff = min(compare_end_utc, complete_boundary_utc)
    read_start_utc = min(
        day_start.astimezone(UTC) - timedelta(days=1),
        compare_end_utc - timedelta(days=31),
    )
    read_end_utc = compare_end_utc + timedelta(days=1)

    async with store.AsyncSession() as session:
        result = await session.execute(
            select(
                SlotObservation.slot_start,
                SlotObservation.import_kwh,
                SlotObservation.import_price_sek_kwh,
                SlotObservation.export_kwh,
                SlotObservation.export_price_sek_kwh,
                SlotObservation.pv_kwh,
                SlotObservation.load_kwh,
                SlotObservation.water_kwh,
                SlotObservation.ev_charging_kwh,
                SlotObservation.batt_charge_kwh,
                SlotObservation.batt_discharge_kwh,
                SlotObservation.soc_start_percent,
                SlotObservation.soc_end_percent,
                SlotObservation.quality_flags,
            ).where(
                # Wide ISO bounds keep offset-formatted rows around DST; precise
                # selected-period and completed-slot filtering happens in UTC below.
                SlotObservation.slot_start >= read_start_utc.astimezone(tz).isoformat(),
                SlotObservation.slot_start < read_end_utc.astimezone(tz).isoformat(),
            )
        )
        rows = result.fetchall()
        # Include the single immediately preceding completed slot when the first
        # selected observation has no start SoC. Comparison code verifies contiguity.
        prior_result = await session.execute(
            select(SlotObservation.slot_start, SlotObservation.soc_end_percent).where(
                SlotObservation.slot_start >= (day_start - timedelta(minutes=30)).isoformat(),
                SlotObservation.slot_start < day_start.isoformat(),
            )
        )
        prior_rows = prior_result.fetchall()

    # Parse once and order chronologically (not by string, so DST changes sort correctly).
    slots: list[tuple[datetime, Any]] = []
    for row in rows:
        try:
            start = datetime.fromisoformat(str(row[0]))
        except ValueError:
            continue
        local = start.astimezone(tz) if start.tzinfo else tz.localize(start)
        slots.append((local, row))
    slots.sort(key=lambda item: item[0])

    def observation(row: Any, local: datetime) -> RecordedObservation:
        return RecordedObservation(
            start=local,
            import_kwh=None if row[1] is None else float(row[1]),
            import_price=None if row[2] is None else float(row[2]),
            export_kwh=None if row[3] is None else float(row[3]),
            export_price=None if row[4] is None else float(row[4]),
            pv_kwh=None if row[5] is None else float(row[5]),
            load_kwh=None if row[6] is None else float(row[6]),
            water_kwh=None if row[7] is None else float(row[7]),
            ev_kwh=None if row[8] is None else float(row[8]),
            charge_kwh=None if row[9] is None else float(row[9]),
            discharge_kwh=None if row[10] is None else float(row[10]),
            soc_start_percent=None if row[11] is None else float(row[11]),
            soc_end_percent=None if row[12] is None else float(row[12]),
            quality_flags=row[13],
        )

    selected_slots = [
        (local, row)
        for local, row in slots
        if local.date() >= query_start
        and local.date() <= query_end
        and local.astimezone(UTC) < compare_end_utc
    ]
    selected_complete = [
        (local, row)
        for local, row in selected_slots
        if local.astimezone(UTC) + timedelta(minutes=15) <= comparison_cutoff
    ]
    expected_starts: list[datetime] = []
    expected_cursor = day_start.astimezone(UTC)
    while expected_cursor < comparison_cutoff:
        expected_starts.append(expected_cursor)
        expected_cursor += timedelta(minutes=15)
    selected_start_keys = {local.astimezone(UTC) for local, _ in selected_complete}
    missing_completed_slot = any(start not in selected_start_keys for start in expected_starts)
    all_observations = [observation(row, local) for local, row in slots]
    prior_soc: float | None = None
    if selected_complete:
        first_utc = selected_complete[0][0].astimezone(UTC)
        candidate_prior = [
            (local, float(row[12]))
            for local, row in slots
            if row[12] is not None and local.astimezone(UTC) + timedelta(minutes=15) == first_utc
        ]
        if candidate_prior:
            prior_soc = candidate_prior[-1][1]
        else:
            for raw_start, raw_soc in prior_rows:
                try:
                    parsed = datetime.fromisoformat(str(raw_start))
                    parsed = parsed.astimezone(tz) if parsed.tzinfo else tz.localize(parsed)
                except (ValueError, TypeError):
                    continue
                if (
                    parsed.astimezone(UTC) + timedelta(minutes=15) == first_utc
                    and raw_soc is not None
                ):
                    prior_soc = float(raw_soc)
    slots = selected_slots

    # Per bucket: import cost, export revenue, baseline import cost, baseline export revenue.
    buckets: dict[datetime, list[float]] = {}
    real_charge_kwh = real_discharge_kwh = 0.0
    for local, row in slots:
        key = local.replace(minute=0, second=0, microsecond=0)
        if not hourly:
            key = key.replace(hour=0)
        bucket = buckets.setdefault(key, [0.0, 0.0, 0.0, 0.0])
        bucket[0] += float(row[1] or 0.0) * float(row[2] or 0.0)
        bucket[1] += float(row[3] or 0.0) * float(row[4] or 0.0)
        real_charge_kwh += float(row[9] or 0.0)
        real_discharge_kwh += float(row[10] or 0.0)

    baseline_summary: dict[str, float | None] | None = None
    if battery is not None and slots:
        simulation = simulate_self_use_with_end_state(
            [
                BaselineSlot(
                    pv_kwh=float(row[5] or 0.0),
                    load_kwh=float(row[6] or 0.0),
                    water_kwh=float(row[7] or 0.0),
                    ev_kwh=float(row[8] or 0.0),
                    soc_end_percent=None if row[12] is None else float(row[12]),
                )
                for _, row in slots
            ],
            battery,
            prior_soc,
        )
        flows = simulation.flows
        baseline_charge_kwh = baseline_discharge_kwh = 0.0
        for (local, row), flow in zip(slots, flows, strict=True):
            key = local.replace(minute=0, second=0, microsecond=0)
            if not hourly:
                key = key.replace(hour=0)
            bucket = buckets[key]
            bucket[2] += flow.import_kwh * float(row[2] or 0.0)
            bucket[3] += flow.export_kwh * float(row[4] or 0.0)
            baseline_charge_kwh += flow.charge_kwh
            baseline_discharge_kwh += flow.discharge_kwh

        cycle_cost_kwh = float(
            config.get("battery_economics", {}).get("battery_cycle_cost_kwh", 0.0)
        )
        baseline_net = sum(b[2] - b[3] for b in buckets.values())
        baseline_wear = (baseline_charge_kwh + baseline_discharge_kwh) * cycle_cost_kwh * 0.5
        real_net = sum(b[0] - b[1] for b in buckets.values())
        real_wear = (real_charge_kwh + real_discharge_kwh) * cycle_cost_kwh * 0.5

        # Energy left in the battery at the end of the period is worth something: value the
        # difference between the real and the simulated end state at the period's average
        # import price, net of the discharge loss. Unknown real end SoC means no adjustment.
        real_end_soc = next((float(r[12]) for _, r in reversed(slots) if r[12] is not None), None)
        stored_diff_kwh: float | None = None
        stored_value_sek: float | None = None
        if real_end_soc is not None:
            stored_diff_kwh = (
                (real_end_soc - simulation.end_soc_percent) / 100.0 * battery.capacity_kwh
            )
            prices = [float(r[2]) for _, r in slots if r[2] is not None]
            avg_import_price = sum(prices) / len(prices) if prices else 0.0
            stored_value_sek = stored_diff_kwh * avg_import_price * battery.discharge_efficiency
        baseline_summary = {
            "net_cost_sek": round(baseline_net, 3),
            "battery_wear_cost_sek": round(baseline_wear, 3),
            "net_cost_incl_wear_sek": round(baseline_net + baseline_wear, 3),
            "saving_incl_wear_sek": round(
                (baseline_net + baseline_wear) - (real_net + real_wear) + (stored_value_sek or 0.0),
                3,
            ),
            "stored_energy_difference_kwh": (
                None if stored_diff_kwh is None else round(stored_diff_kwh, 3)
            ),
            "stored_energy_value_sek": (
                None if stored_value_sek is None else round(stored_value_sek, 3)
            ),
        }

    battery_comparison: dict[str, Any]
    if battery is None:
        battery_comparison = {
            "status": "no_battery",
            "reason": "battery_not_configured",
            "method_version": METHOD_VERSION,
        }
    elif not expected_starts or not selected_complete:
        battery_comparison = {
            "status": "no_data",
            "reason": "no_completed_observations",
            "method_version": METHOD_VERSION,
        }
    elif missing_completed_slot:
        battery_comparison = {
            "status": "incomplete_period",
            "reason": "missing_completed_slot",
            "method_version": METHOD_VERSION,
            "through": (
                comparison_cutoff.isoformat()
                if comparison_cutoff > day_start.astimezone(UTC)
                else None
            ),
        }
    else:
        fit_end = comparison_cutoff
        latest_completed = max(
            (item.start for item in all_observations if item.start.astimezone(UTC) < fit_end),
            default=None,
        )
        fit = await _calibrated_fit(
            store,
            battery,
            config,
            all_observations,
            fit_end,
            latest_completed or fit_end,
        )
        if fit.status != "available" or fit.diagnostics is None:
            battery_comparison = {
                "status": fit.status,
                "reason": fit.reason,
                "method_version": METHOD_VERSION,
                "through": (
                    selected_complete[-1][0].astimezone(UTC) + timedelta(minutes=15)
                ).isoformat(),
            }
            if fit.diagnostics is not None:
                battery_comparison["calibration"] = fit.diagnostics.as_dict()
        else:
            comp_battery = ComparisonBattery(
                capacity_kwh=battery.capacity_kwh,
                min_soc_percent=battery.min_soc_percent,
                max_soc_percent=battery.max_soc_percent,
                max_charge_w=battery.max_charge_w,
                max_discharge_w=battery.max_discharge_w,
            )

            def comparison_bucket(start: datetime) -> str:
                local = start.astimezone(tz)
                key = local.replace(minute=0, second=0, microsecond=0)
                if not hourly:
                    key = tz.localize(datetime(local.year, local.month, local.day))
                return key.isoformat()

            comparison, failure_reason = build_comparison(
                [observation(row, local) for local, row in selected_complete],
                prior_soc,
                comp_battery,
                fit.diagnostics,
                float(config.get("battery_economics", {}).get("battery_cycle_cost_kwh", 0.0)),
                comparison_bucket,
            )
            if comparison is None:
                battery_comparison = {
                    "status": (
                        "unreliable_model"
                        if failure_reason == "period_validation_failed"
                        else "incomplete_period"
                    ),
                    "reason": failure_reason or "period_invalid",
                    "method_version": METHOD_VERSION,
                    "through": (
                        selected_complete[-1][0].astimezone(UTC) + timedelta(minutes=15)
                    ).isoformat(),
                    "calibration": fit.diagnostics.as_dict(),
                }
            else:
                battery_comparison = comparison

    points: list[dict[str, Any]] = []
    cumulative = 0.0
    baseline_cumulative = 0.0
    for key in sorted(buckets):
        import_cost, export_rev, baseline_import_cost, baseline_export_rev = buckets[key]
        cumulative += import_cost - export_rev
        point: dict[str, Any] = {
            "start": key.isoformat(),
            "import_cost_sek": round(import_cost, 3),
            "export_revenue_sek": round(export_rev, 3),
            "net_cost_sek": round(import_cost - export_rev, 3),
            "cumulative_net_cost_sek": round(cumulative, 3),
        }
        if baseline_summary is not None:
            baseline_cumulative += baseline_import_cost - baseline_export_rev
            point["baseline_cumulative_net_cost_sek"] = round(baseline_cumulative, 3)
        points.append(point)

    return {
        "period": period,
        "start_date": query_start.isoformat(),
        "end_date": query_end.isoformat(),
        "bucket": "hour" if hourly else "day",
        "points": points,
        "baseline": baseline_summary,
        "battery_comparison": battery_comparison,
    }
