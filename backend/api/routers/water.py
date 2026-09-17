import logging
import traceback
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("darkstar.api.water")

router = APIRouter(prefix="/api/water", tags=["water"])


@router.get(
    "/boost",
    summary="Get Water Boost Status",
    description="Get current water boost status from executor.",
)
async def get_water_boost() -> dict[str, Any]:
    """Get current water boost status from executor."""
    from backend.api.routers.executor import get_executor_instance

    executor = get_executor_instance()
    if not executor:
        return {
            "boost": False,
            "active": False,
            "heaters": {},
            "expires_at": None,
            "source": "no_executor",
        }

    if hasattr(executor, "get_water_boost_status"):
        status = executor.get_water_boost_status() or {}
        return {
            "boost": bool(status.get("active")),
            "active": bool(status.get("active")),
            "heaters": status.get("heaters", {}),
            "expires_at": status.get("expires_at"),
            "source": "executor",
        }
    return {"boost": False, "active": False, "heaters": {}, "source": "executor"}


class WaterBoostRequest(BaseModel):
    duration_minutes: int = 60
    heater_ids: list[str] | None = None


@router.post(
    "/boost",
    summary="Set Water Boost",
    description="Activate water heater boost via executor quick action.",
)
async def set_water_boost(req: WaterBoostRequest) -> dict[str, Any]:
    """Activate water heater boost via executor quick action."""
    try:
        from backend.api.routers.executor import (
            get_executor_instance,
        )

        executor = get_executor_instance()
        if not executor:
            logger.error("Executor unavailable for water boost")
            raise HTTPException(503, "Executor not available")
        if hasattr(executor, "set_water_boost"):
            result = executor.set_water_boost(  # pyright: ignore [reportUnknownMemberType]
                duration_minutes=req.duration_minutes,
                heater_ids=req.heater_ids,
            )
            if not result.get("success"):
                logger.error(f"Failed to set water boost: {result.get('error')}")
                status_code = 400 if result.get("unknown_heater_ids") else 500
                raise HTTPException(
                    status_code, f"Failed to set water boost: {result.get('error')}"
                )

            logger.info(f"Water boost activated successfully for {req.duration_minutes} minutes")
            return {
                "status": "success",
                "message": f"Water boost activated for {req.duration_minutes} minutes",
            }

        logger.error("Executor missing set_water_boost method")
        raise HTTPException(501, "Water boost not supported by executor")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting water boost: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"Internal error setting water boost: {e}") from e


@router.delete(
    "/boost",
    summary="Cancel Water Boost",
    description="Cancel active water boost.",
)
async def cancel_water_boost(req: WaterBoostRequest | None = None) -> dict[str, Any]:
    """Cancel active water boost."""
    try:
        from backend.api.routers.executor import (
            get_executor_instance,
        )

        executor = get_executor_instance()
        if executor and hasattr(executor, "clear_water_boost"):
            result = executor.clear_water_boost(heater_ids=req.heater_ids if req else None)
            if not result.get("success"):
                status_code = 400 if result.get("unknown_heater_ids") else 500
                raise HTTPException(
                    status_code, f"Failed to cancel water boost: {result.get('error')}"
                )
            logger.info("Water boost cancelled successfully")
        return {"status": "success", "message": "Water boost cancelled"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling water boost: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"Internal error cancelling water boost: {e}") from e
