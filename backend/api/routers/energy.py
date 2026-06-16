import logging
from datetime import date, datetime, timedelta
from typing import Any, cast

from fastapi import APIRouter, Depends

from backend.api.deps import get_learning_store
from backend.core.secrets import load_yaml
from backend.learning.store import LearningStore

logger = logging.getLogger("darkstar.api.energy")

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


@router.get(
    "/energy/today",
    summary="Get Today's Energy",
    description="Get today's energy summary from database (SlotObservation table).",
)
async def get_energy_today(
    store: LearningStore = Depends(get_learning_store),
) -> dict[str, float]:
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
    water_kwh = range_data.get("water_heating_kwh", 0.0)
    net_cost = range_data.get("net_cost_sek", 0.0)
    battery_wear_cost = range_data.get("battery_wear_cost_sek", 0.0)
    net_cost_incl_wear = range_data.get("net_cost_incl_wear_sek", 0.0)

    # Calculate battery cycles
    config = load_yaml("config.yaml")
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
        "water_heating_kwh": round(water_kwh, 2),
        "net_cost_sek": round(net_cost, 2),
        "battery_wear_cost_sek": round(battery_wear_cost, 2),
        "net_cost_incl_wear_sek": round(net_cost_incl_wear, 2),
        "battery_cycles": round(battery_cycles, 2),
        # Legacy aliases (for backwards compatibility during transition)
        "solar": round(pv_kwh, 2),
        "consumption": round(load_kwh, 2),
        "grid_import": round(grid_imp_kwh, 2),
        "grid_export": round(grid_exp_kwh, 2),
        "net_cost_kr": round(net_cost, 2),
    }


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

        # Determine date range based on period or custom dates
        query_start: date = today_local
        query_end: date = today_local

        if period == "custom" and start_date and end_date:
            # Parse custom dates (YYYY-MM-DD format)
            try:
                custom_start = datetime.strptime(start_date, "%Y-%m-%d").date()
                custom_end = datetime.strptime(end_date, "%Y-%m-%d").date()

                # Validate date range
                if custom_end < custom_start:
                    raise ValueError("End date must be after start date")

                query_start = custom_start
                query_end = custom_end
            except ValueError as e:
                if "does not match format" in str(e):
                    raise ValueError("Invalid date format. Use YYYY-MM-DD") from e
                raise
        elif period == "today":
            query_start = query_end = today_local
        elif period == "yesterday":
            query_end = today_local - timedelta(days=1)
            query_start = query_end
        elif period == "week":
            query_end = today_local
            query_start = today_local - timedelta(days=6)
        elif period == "month":
            query_end = today_local
            query_start = today_local - timedelta(days=29)

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
