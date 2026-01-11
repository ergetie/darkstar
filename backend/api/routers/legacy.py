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
    result = await planner_service.run_once()

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


@router.get("/api/initial_state")
async def initial_state() -> dict[str, Any]:
    """Bootstrap state for frontend."""
    # Simplified version
    return {"user": {"name": "User"}, "config": {}, "notifications": []}
