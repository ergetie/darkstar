"""
Analyst API Router - Rev ARC3

Provides endpoints for strategy analysis and advice generation.
"""

import logging
from typing import Any

from fastapi import APIRouter

from inputs import load_yaml

logger = logging.getLogger("darkstar.api.analyst")

router = APIRouter(prefix="/api/analyst", tags=["analyst"])


def _get_strategy_advice() -> dict[str, Any]:
    """Generate strategy advice based on current conditions."""
    try:
        config = load_yaml("config.yaml")
        s_index_cfg = config.get("s_index", {})
        risk_appetite = s_index_cfg.get("risk_appetite", 3)

        # Basic rule-based advice
        advice_items = []

        if risk_appetite <= 2:
            advice_items.append({
                "category": "risk",
                "message": "Conservative risk profile active. Battery will maintain higher reserves.",
                "priority": "info",
            })
        elif risk_appetite >= 4:
            advice_items.append({
                "category": "risk",
                "message": "Aggressive risk profile active. Consider lowering if forecast accuracy is poor.",
                "priority": "warning",
            })

        # Check for vacation mode
        learning_cfg = config.get("learning", {})
        if learning_cfg.get("vacation_mode_enabled", False):
            advice_items.append({
                "category": "mode",
                "message": "Vacation mode is active. Water heating is in anti-legionella mode.",
                "priority": "info",
            })

        # Battery wear cost check
        battery_econ = config.get("battery_economics", {})
        cycle_cost = battery_econ.get("battery_cycle_cost_kwh", 0.05)
        if cycle_cost > 0.15:
            advice_items.append({
                "category": "battery",
                "message": f"High battery cycle cost ({cycle_cost} SEK/kWh). Arbitrage may be limited.",
                "priority": "warning",
            })

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
    return _get_strategy_advice()


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
        advice = _get_strategy_advice()

        return {
            "status": "success",
            "advice": advice.get("advice", []),
            "recent_events": history,
            "message": "Analysis completed",
        }
    except ImportError:
        return {
            "status": "partial",
            "advice": _get_strategy_advice().get("advice", []),
            "recent_events": [],
            "message": "Strategy history module not available",
        }
    except Exception as e:
        logger.exception("Strategy analysis failed")
        return {"status": "error", "message": str(e)}
