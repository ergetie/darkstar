import asyncio
import logging
from typing import Any

from fastapi import APIRouter

from backend.api.routers import config, executor, schedule, system

# We'll use the specific response models if they exist, or just Dict[str, Any]
# For bundles, usually we prefer a unified Pydantic model.

logger = logging.getLogger("darkstar.api.dashboard")
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

@router.get(
    "/bundle",
    summary="Get Dashboard Bundle",
    description="Aggregate critical data for the Dashboard (Status, Config, Schedule, Executor, Scheduler) in a single call.",
)
async def get_dashboard_bundle() -> dict[str, Any]:
    """Aggregate all critical dashboard data into a single response."""
    # Run all critical API handler logics in parallel
    # NOTE: We call the handler functions directly to avoid HTTP overhead.
    # We must ensure we are calling the 'decorated' functions correctly or the implementation ones.

    tasks = [
        system.get_system_status(),
        config.get_config(),
        schedule.get_schedule(),
        executor.get_executor_status_snapshot(),
        schedule.get_scheduler_status(),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # helper to handle failure in one sub-task gracefully
    def val(res):
        if isinstance(res, Exception):
            logger.error(f"Bundle sub-task failed: {res}")
            return None
        return res

    return {
        "status": val(results[0]),
        "config": val(results[1]),
        "schedule": val(results[2]),
        "executor_status": val(results[3]),
        "scheduler_status": val(results[4]),
    }
