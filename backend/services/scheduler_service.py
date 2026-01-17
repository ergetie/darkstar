"""
Async Scheduler Service

Background task that runs the planner on a configurable interval.
Replaces the legacy standalone scheduler script.
"""

import asyncio
import contextlib
import logging
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from backend.services.planner_service import PlannerResult, planner_service

logger = logging.getLogger("darkstar.services.scheduler")


@dataclass
class SchedulerStatus:
    """Current state of the scheduler service."""

    running: bool = False
    enabled: bool = False
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    last_run_status: str | None = None
    last_error: str | None = None
    current_task: str = "idle"  # "idle", "planning", "ml_training"


class SchedulerService:
    """Async scheduler service running as FastAPI background task."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._status = SchedulerStatus()

    @property
    def status(self) -> SchedulerStatus:
        """Get current scheduler status."""
        return self._status

    async def start(self) -> None:
        """Start the scheduler background loop."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        self._status.running = True
        self._task = asyncio.create_task(self._loop(), name="scheduler_loop")
        logger.info("Scheduler started")

    async def stop(self) -> None:
        """Gracefully stop the scheduler."""
        self._running = False
        self._status.running = False

        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self._task, timeout=5.0)
            self._task = None

        logger.info("Scheduler stopped")

    async def trigger_now(self) -> PlannerResult:
        """Manually trigger an immediate planner run."""
        self._status.current_task = "planning"
        try:
            result = await planner_service.run_once()
            self._update_status_from_result(result)
            return result
        finally:
            self._status.current_task = "idle"

    async def _loop(self) -> None:
        """Main scheduler loop."""
        logger.info("Scheduler loop started")

        # Initialize next run time
        config = self._load_config()
        self._status.enabled = config.get("enabled", False)

        if self._status.enabled:
            # Run 10 seconds after startup instead of waiting full interval
            self._status.next_run_at = datetime.now(UTC) + timedelta(seconds=10)

        while self._running:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds

                # Reload config (allows live enable/disable)
                config = self._load_config()
                self._status.enabled = config.get("enabled", False)

                if not self._status.enabled:
                    continue

                # Check if it's time to run
                now = datetime.now(UTC)
                if self._status.next_run_at and now >= self._status.next_run_at:
                    await self._run_scheduled(config)

            except asyncio.CancelledError:
                logger.info("Scheduler loop cancelled")
                break
            except Exception as e:
                logger.exception(f"Scheduler loop error: {e}")
                await asyncio.sleep(60)  # Back off on error

    async def _run_scheduled(self, config: dict[str, Any]) -> None:
        """Execute a scheduled planner run."""
        self._status.current_task = "planning"

        try:
            result = await planner_service.run_once()
            self._update_status_from_result(result)

            if not result.success:
                # Smart retry on failure
                await self._smart_retry()

        finally:
            self._status.current_task = "idle"

            # Schedule next run
            self._status.next_run_at = self._compute_next_run(
                datetime.now(UTC),
                config.get("every_minutes", 60),
                config.get("jitter_minutes", 0),
            )

    async def _smart_retry(self) -> None:
        """Retry planner after failure with exponential backoff."""
        retry_delays = [60, 120, 300]  # 1min, 2min, 5min

        for delay in retry_delays:
            if not self._running:
                break

            logger.info(f"Smart retry in {delay}s...")
            await asyncio.sleep(delay)

            result = await planner_service.run_once()
            self._update_status_from_result(result)

            if result.success:
                logger.info("Smart retry succeeded")
                break

    def _update_status_from_result(self, result: PlannerResult) -> None:
        """Update scheduler status from planner result."""
        self._status.last_run_at = result.planned_at
        self._status.last_run_status = "success" if result.success else "error"
        self._status.last_error = result.error

    def _compute_next_run(
        self, from_time: datetime, every_minutes: int, jitter_minutes: int
    ) -> datetime:
        """Calculate next run time with optional jitter."""
        base = from_time + timedelta(minutes=every_minutes)
        if jitter_minutes > 0:
            jitter = random.randint(-jitter_minutes, jitter_minutes)
            base += timedelta(minutes=jitter)
        return base

    def _load_config(self) -> dict[str, Any]:
        """Load scheduler config from config.yaml."""
        try:
            with Path("config.yaml").open() as f:
                cfg = yaml.safe_load(f) or {}

            automation = cfg.get("automation", {})
            schedule = automation.get("schedule", {})

            return {
                "enabled": bool(automation.get("enable_scheduler", False)),
                "every_minutes": int(schedule.get("every_minutes", 60)),
                "jitter_minutes": int(schedule.get("jitter_minutes", 0)),
            }
        except Exception as e:
            logger.warning(f"Failed to load scheduler config: {e}")
            return {"enabled": False, "every_minutes": 60, "jitter_minutes": 0}


# Global singleton
scheduler_service = SchedulerService()
