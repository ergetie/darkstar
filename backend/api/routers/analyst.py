"""
Analyst API Router - Rev ARC3

Provides endpoints for strategy analysis and advice generation.
"""

import logging
from datetime import datetime
from typing import Any

import pytz
from fastapi import APIRouter

from backend.core.secrets import load_yaml

logger = logging.getLogger("darkstar.api.analyst")

router = APIRouter(prefix="/api/analyst", tags=["analyst"])

# Price advice thresholds (see openspec/changes/price-alert-accuracy/design.md)
PRICE_DROP_RELATIVE_THRESHOLD = 0.70  # a day's avg must be <=70% of today's (30%+ drop)
PRICE_DROP_MIN_ABSOLUTE_SEK = 0.15  # ...and at least this much cheaper in absolute terms
PRICE_WINDOW_RATIO_THRESHOLD = 0.75  # a window avg must be <=75% of the daily avg (25%+ below)


def _get_price_advice(
    daily_outlook: list[dict[str, Any]],
    today_avg_spot: float,
    overnight_avg: float | None,
    midday_avg: float | None,
) -> list[dict[str, Any]]:
    """
    Generate price-related advice items based on forecast data.

    Rules:
    1. Cheapest day ahead: any day D+1..D+7 is >=30% and >=0.15 SEK/kWh cheaper than today
    2. Prices rising: every day D+1..D+3 is higher than today
    3. Cheap overnight, else solar midday: tonight's 22:00-06:00 window average is 25%+
       below D+1's daily average; if not, D+1's 10:00-16:00 window is checked instead

    Args:
        daily_outlook: List of daily outlook dicts (D+1 through D+7)
        today_avg_spot: Today's actual average spot price for comparison
        overnight_avg: Latest-issue p50 average over tonight's 22:00-06:00 window, or None
        midday_avg: Latest-issue p50 average over tomorrow's 10:00-16:00 window, or None

    Returns:
        List of advice dicts with category="price", message, and priority
    """
    advice_items: list[dict[str, Any]] = []

    if not daily_outlook or today_avg_spot <= 0:
        return advice_items

    # Rule 1: Cheapest day ahead
    cheapest_day = None
    max_drop_pct = 0.0

    for day in daily_outlook:
        day_avg = day.get("avg_spot_p50", 0)
        if day_avg <= 0:
            continue
        absolute_drop = today_avg_spot - day_avg
        is_relative_drop = day_avg <= today_avg_spot * PRICE_DROP_RELATIVE_THRESHOLD
        is_absolute_drop = absolute_drop >= PRICE_DROP_MIN_ABSOLUTE_SEK
        if is_relative_drop and is_absolute_drop:
            drop_pct = absolute_drop / today_avg_spot * 100
            if drop_pct > max_drop_pct:
                max_drop_pct = drop_pct
                cheapest_day = day

    if cheapest_day:
        advice_items.append(
            {
                "category": "price",
                "message": f"Prices drop ~{max_drop_pct:.0f}% on {cheapest_day['day_label']}. Consider deferring heavy loads.",
                "priority": "info",
            }
        )

    # Rule 2: Prices rising (D+1 through D+3 all higher than today)
    d1_to_d3 = [d for d in daily_outlook if d.get("days_ahead", 0) <= 3]

    if len(d1_to_d3) >= 3:
        all_higher = all(d.get("avg_spot_p50", float("inf")) > today_avg_spot for d in d1_to_d3[:3])
        if all_higher:
            advice_items.append(
                {
                    "category": "price",
                    "message": "Prices rising all week — today is the cheapest day in the next 3 days.",
                    "priority": "info",
                }
            )

    # Rule 3: Cheap overnight window, falling back to solar midday
    d1 = next((d for d in daily_outlook if d.get("days_ahead") == 1), None)
    if d1:
        d1_avg = d1.get("avg_spot_p50", 0)
        if (
            d1_avg > 0
            and overnight_avg is not None
            and overnight_avg <= d1_avg * PRICE_WINDOW_RATIO_THRESHOLD
        ):
            advice_items.append(
                {
                    "category": "price",
                    "message": "Tonight 22:00-06:00 has the lowest prices — ideal for heavy loads.",
                    "priority": "info",
                }
            )
        elif (
            d1_avg > 0
            and midday_avg is not None
            and midday_avg <= d1_avg * PRICE_WINDOW_RATIO_THRESHOLD
        ):
            advice_items.append(
                {
                    "category": "price",
                    "message": "Midday solar hours have the lowest prices tomorrow — ideal for heavy loads.",
                    "priority": "info",
                }
            )

    return advice_items


async def _get_today_avg_spot_price(config: dict[str, Any]) -> float | None:
    """Average of today's actual day-ahead spot prices (SEK/kWh, no fees), or None if unavailable."""
    from backend.core.prices import get_nordpool_data

    tz = pytz.timezone(config.get("timezone", "Europe/Stockholm"))
    today = datetime.now(tz).date()

    prices = await get_nordpool_data()
    today_values = [
        slot["export_price_sek_kwh"] for slot in prices if slot["start_time"].date() == today
    ]

    if not today_values:
        return None

    return sum(today_values) / len(today_values)


async def _get_strategy_advice() -> dict[str, Any]:
    """Generate strategy advice based on current conditions."""
    try:
        config = load_yaml("config.yaml")
        s_index_cfg = config.get("s_index", {})
        risk_appetite = s_index_cfg.get("risk_appetite", 3)

        # Basic rule-based advice
        advice_items: list[dict[str, Any]] = []

        if risk_appetite <= 2:
            advice_items.append(
                {
                    "category": "risk",
                    "message": "Conservative risk profile active. Battery will maintain higher reserves.",
                    "priority": "info",
                }
            )
        elif risk_appetite >= 4:
            advice_items.append(
                {
                    "category": "risk",
                    "message": "Aggressive risk profile active. Consider lowering if forecast accuracy is poor.",
                    "priority": "warning",
                }
            )

        # Check for vacation mode
        learning_cfg = config.get("learning", {})
        if learning_cfg.get("vacation_mode_enabled", False):
            advice_items.append(
                {
                    "category": "mode",
                    "message": "Vacation mode is active. Water heating is in anti-legionella mode.",
                    "priority": "info",
                }
            )

        # Battery wear cost check
        battery_econ = config.get("battery_economics", {})
        cycle_cost = battery_econ.get("battery_cycle_cost_kwh", 0.05)
        if cycle_cost > 0.15:
            advice_items.append(
                {
                    "category": "battery",
                    "message": f"High battery cycle cost ({cycle_cost} SEK/kWh). Arbitrage may be limited.",
                    "priority": "warning",
                }
            )

        # Check if price forecasting is enabled and add price advice
        price_forecast_cfg = config.get("price_forecast", {})
        if price_forecast_cfg.get("enabled", False):
            try:
                # Import price outlook helpers
                from backend.core.forecasts import get_forecast_db_path
                from backend.core.price_outlook import get_daily_outlook, get_price_window_averages

                db_path = get_forecast_db_path()
                daily_outlook = get_daily_outlook(db_path)

                if daily_outlook:
                    today_avg_spot = await _get_today_avg_spot_price(config)

                    if today_avg_spot is not None:
                        window_averages = get_price_window_averages(db_path)
                        price_advice = _get_price_advice(
                            daily_outlook,
                            today_avg_spot,
                            window_averages["overnight_avg"],
                            window_averages["midday_avg"],
                        )
                        advice_items.extend(price_advice)
            except Exception as e:
                # Log but don't fail if price advice generation fails
                logger.debug(f"Could not generate price advice: {e}")

        return {
            "advice": advice_items,
            "count": len(advice_items),
            "source": "rule_based",
        }
    except Exception as e:
        logger.warning(f"Failed to generate advice: {e}")
        return {"advice": [], "count": 0, "error": str(e)}


@router.get(
    "/advice",
    summary="Get Strategy Advice",
    description="Returns rule-based or LLM-generated strategy advice.",
)
async def get_advice() -> dict[str, Any]:
    """Get strategy advice based on current conditions."""
    return await _get_strategy_advice()


@router.get(
    "/run",
    summary="Run Strategy Analysis",
    description="Triggers a full strategy analysis and returns recommendations.",
)
async def run_analysis() -> dict[str, Any]:
    """Run strategy analysis and return recommendations."""
    try:
        from backend.strategy.history import get_strategy_history

        # Get recent strategy events
        history = get_strategy_history(limit=10)

        # Get current advice
        advice = await _get_strategy_advice()

        return {
            "status": "success",
            "advice": advice.get("advice", []),
            "recent_events": history,
            "message": "Analysis completed",
        }
    except ImportError:
        return {
            "status": "partial",
            "advice": (await _get_strategy_advice()).get("advice", []),
            "recent_events": [],
            "message": "Strategy history module not available",
        }
    except Exception as e:
        logger.exception("Strategy analysis failed")
        return {"status": "error", "message": str(e)}
