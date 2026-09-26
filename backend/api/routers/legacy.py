import logging
from typing import Any

from fastapi import APIRouter

from backend.services.planner_service import planner_service

logger = logging.getLogger("darkstar.api.legacy")

router = APIRouter(tags=["legacy"])


@router.post("/api/run_planner")
async def run_planner() -> dict[str, Any]:
    """Manually trigger the planner (in-process, non-blocking).

    Uses asyncio.to_thread() internally to avoid blocking the event loop.
    Returns structured response with timing and slot count.
    """
    # If a run is in progress, wait for the coalesced follow-up instead of erroring.
    result = await planner_service.run_once(wait=True)

    if result.success:
        return {
            "status": "ok",
            "message": f"Planner completed: {result.slot_count} slots in {result.duration_ms:.0f}ms",
            "slot_count": result.slot_count,
            "duration_ms": result.duration_ms,
        }
    else:
        return {
            "status": "error",
            "message": result.error or "Unknown error",
        }


@router.get("/api/planner/status")
async def planner_status() -> dict[str, Any]:
    """Get current planner execution status.

    Returns:
        phase: Current execution phase (idle, fetching_prices, etc.)
        elapsed_ms: Time elapsed in current phase
        is_running: Whether planner is currently executing
    """
    return planner_service.get_status()


@router.get("/api/initial_state")
async def initial_state() -> dict[str, Any]:
    """Bootstrap state for frontend."""
    # Simplified version
    return {"user": {"name": "User"}, "config": {}, "notifications": []}
