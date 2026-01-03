"""
Async Planner Service

Wraps the blocking PlannerPipeline in an async interface suitable
for running inside the FastAPI process without blocking the event loop.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from backend.core.cache import cache
from backend.core.websockets import ws_manager

logger = logging.getLogger("darkstar.services.planner")


@dataclass
class PlannerResult:
    """Result of a planner execution."""

    success: bool
    planned_at: datetime
    slot_count: int = 0
    error: str | None = None
    duration_ms: float = 0


class PlannerService:
    """Async planner service for in-process execution."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def run_once(self) -> PlannerResult:
        """
        Run the planner in a threadpool to avoid blocking the event loop.
        Handles cache invalidation and WebSocket notification automatically.

        Uses a lock to prevent concurrent planner executions.
        """
        # Prevent concurrent runs
        if self._lock.locked():
            logger.warning("Planner already running, skipping concurrent request")
            return PlannerResult(
                success=False,
                planned_at=datetime.now(),
                error="Planner already running",
            )

        async with self._lock:
            start = datetime.now()

            try:
                # Run blocking planner code in threadpool
                result = await asyncio.to_thread(self._run_sync)
                result.duration_ms = (datetime.now() - start).total_seconds() * 1000

                if result.success:
                    # Invalidate cache and emit WebSocket event
                    await self._notify_success(result)
                else:
                    await self._notify_error(result)

                return result

            except Exception as e:
                logger.exception("Planner execution failed")
                result = PlannerResult(
                    success=False,
                    planned_at=start,
                    error=str(e),
                    duration_ms=(datetime.now() - start).total_seconds() * 1000,
                )
                await self._notify_error(result)
                return result

    def _run_sync(self) -> PlannerResult:
        """Blocking planner execution (runs in threadpool)."""
        from bin.run_planner import main as run_planner_main

        planned_at = datetime.now()

        try:
            exit_code = run_planner_main()

            if exit_code == 0:
                # Count slots from schedule.json
                slot_count = self._count_schedule_slots()
                return PlannerResult(
                    success=True,
                    planned_at=planned_at,
                    slot_count=slot_count,
                )
            else:
                return PlannerResult(
                    success=False,
                    planned_at=planned_at,
                    error=f"Planner exited with code {exit_code}",
                )
        except Exception as e:
            return PlannerResult(
                success=False,
                planned_at=planned_at,
                error=str(e),
            )

    def _count_schedule_slots(self) -> int:
        """Count slots in schedule.json for metadata."""
        import json

        try:
            with Path("schedule.json").open() as f:
                data = json.load(f)
                return len(data.get("schedule", []))
        except Exception:
            return 0

    async def _notify_success(self, result: PlannerResult) -> None:
        """Invalidate cache and emit WebSocket event on success."""
        try:
            await cache.invalidate("schedule:current")
            await ws_manager.emit(
                "schedule_updated",
                {
                    "planned_at": result.planned_at.isoformat(),
                    "slot_count": result.slot_count,
                    "duration_ms": result.duration_ms,
                    "status": "success",
                },
            )
            logger.info(
                "Planner completed: %d slots in %.0fms",
                result.slot_count,
                result.duration_ms,
            )
        except Exception as e:
            logger.warning(f"Failed to notify success: {e}")

    async def _notify_error(self, result: PlannerResult) -> None:
        """Emit WebSocket error event on failure."""
        try:
            await ws_manager.emit(
                "planner_error",
                {
                    "planned_at": result.planned_at.isoformat(),
                    "error": result.error,
                    "duration_ms": result.duration_ms,
                },
            )
            logger.error("Planner failed: %s", result.error)
        except Exception as e:
            logger.warning(f"Failed to notify error: {e}")


# Global singleton
planner_service = PlannerService()
