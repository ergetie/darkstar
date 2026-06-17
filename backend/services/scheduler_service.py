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

    # ARC11: ML Training Status
    training_enabled: bool = False
    last_training_at: datetime | None = None
    next_training_at: datetime | None = None
    last_training_status: str | None = None

    # Price forecast daily snapshot status
    price_forecast_enabled: bool = False
    last_price_forecast_at: datetime | None = None
    next_price_forecast_at: datetime | None = None


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

    async def trigger_now(
        self,
        ev_plugged_in_override: bool | None = None,
        ev_charger_id_override: str | None = None,
    ) -> PlannerResult:
        """Manually trigger an immediate planner run.

        Args:
            ev_plugged_in_override: If True, passes plugged-in state to planner to avoid REST race
            ev_charger_id_override: Charger ID to apply the plug state override to (Task 7.3)
        """
        self._status.current_task = "planning"
        try:
            result = await planner_service.run_once(
                ev_plugged_in_override=ev_plugged_in_override,
                ev_charger_id_override=ev_charger_id_override,
            )
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

        # Initial training schedule
        self._status.training_enabled = config.get("ml_training", {}).get("enabled", False)
        if self._status.training_enabled:
            self._status.next_training_at = self._compute_next_training(config["ml_training"])

        # Initial price forecast schedule
        self._status.price_forecast_enabled = config.get("price_forecast", {}).get("enabled", False)
        if self._status.price_forecast_enabled:
            self._status.next_price_forecast_at = self._compute_next_price_forecast(
                config.get("price_forecast", {})
            )

        while self._running:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds

                # Reload config (allows live enable/disable)
                config = self._load_config()
                self._status.enabled = config.get("enabled", False)
                self._status.training_enabled = config.get("ml_training", {}).get("enabled", False)
                self._status.price_forecast_enabled = config.get("price_forecast", {}).get(
                    "enabled", False
                )

                # Check Planning
                if self._status.enabled:
                    now = datetime.now(UTC)
                    # Respect planner retry policy: skip if suspended or before retry time
                    if planner_service.retry_suspended:
                        pass  # Config-blocking error: wait for settings_saved event
                    elif planner_service.next_retry_at is not None:
                        retry_at_utc = (
                            planner_service.next_retry_at.replace(tzinfo=UTC)
                            if planner_service.next_retry_at.tzinfo is None
                            else planner_service.next_retry_at
                        )
                        if (
                            now >= retry_at_utc
                            and self._status.next_run_at
                            and now >= self._status.next_run_at
                        ):
                            await self._run_scheduled(config)
                    elif self._status.next_run_at and now >= self._status.next_run_at:
                        await self._run_scheduled(config)

                # Check Training (ARC11)
                if self._status.training_enabled:
                    now = datetime.now(UTC)
                    if (
                        self._status.next_training_at
                        and now >= self._status.next_training_at
                        and self._status.current_task == "idle"
                    ):
                        await self._run_ml_training(config["ml_training"])

                # Check Daily Price Forecast (runs independently at 06:00)
                if self._status.price_forecast_enabled:
                    now = datetime.now(UTC)
                    if (
                        self._status.next_price_forecast_at
                        and now >= self._status.next_price_forecast_at
                        and self._status.current_task == "idle"
                    ):
                        await self._run_price_forecast_daily(config.get("price_forecast", {}))

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

        finally:
            self._status.current_task = "idle"

            # If planner_service has set a retry time, use it; otherwise use the normal cadence
            if planner_service.next_retry_at is not None and not planner_service.retry_suspended:
                retry_utc = (
                    planner_service.next_retry_at.replace(tzinfo=UTC)
                    if planner_service.next_retry_at.tzinfo is None
                    else planner_service.next_retry_at
                )
                self._status.next_run_at = retry_utc
            else:
                self._status.next_run_at = self._compute_next_run(
                    datetime.now(UTC),
                    config.get("every_minutes", 60),
                    config.get("jitter_minutes", 0),
                )

    def _update_status_from_result(self, result: PlannerResult) -> None:
        """Update scheduler status from planner result."""
        self._status.last_run_at = result.planned_at
        self._status.last_run_status = "success" if result.success else "error"
        self._status.last_error = result.error

    async def _run_ml_training(self, config: dict[str, Any]) -> None:
        """Execute a scheduled ML training run (ARC11) with retry logic."""
        from ml.training_orchestrator import train_all_models

        self._status.current_task = "ml_training"
        logger.info("Starting automatic ML training...")

        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            try:
                result = await train_all_models(training_type="automatic")
                self._status.last_training_at = datetime.now(UTC)
                self._status.last_training_status = result.get("status", "unknown")

                if result.get("status") == "error":
                    error_msg = result.get("error", "Unknown error")
                    if attempt < max_attempts:
                        logger.warning(
                            f"Automatic training failed (attempt {attempt}/{max_attempts}): {error_msg}. Retrying in 5 min..."
                        )
                        await asyncio.sleep(300)
                        continue
                    else:
                        logger.error(
                            f"Automatic training failed after {max_attempts} attempts: {error_msg}"
                        )
                else:
                    logger.info(f"Automatic training completed: {result.get('status')}")
                    break

            except Exception as e:
                if attempt < max_attempts:
                    logger.warning(
                        f"Error during automatic ML training (attempt {attempt}/{max_attempts}): {e}. Retrying in 5 min..."
                    )
                    await asyncio.sleep(300)
                else:
                    logger.exception(
                        f"Critical error during automatic ML training after {max_attempts} attempts: {e}"
                    )
                    self._status.last_training_status = "error"

        self._status.current_task = "idle"
        # Schedule next run regardless of success/failure (don't get stuck)
        self._status.next_training_at = self._compute_next_training(config)

    def _compute_next_training(self, config: dict[str, Any]) -> datetime:
        """Calculate next training date based on frequency and run_time.

        Supports daily retraining (default) or weekly on specific days.
        """
        import pytz

        try:
            # Load timezone from global config or default
            with Path("config.yaml").open() as f:
                glob_cfg: dict[str, Any] = yaml.safe_load(f) or {}
            tz_str: str = glob_cfg.get("timezone", "Europe/Stockholm")
            tz = pytz.timezone(tz_str)

            # Check frequency (daily or weekly)
            frequency = config.get("frequency", "daily")

            # Validate run_time (HH:MM)
            run_time_str = config.get("run_time", "03:00")
            try:
                hour, minute = map(int, run_time_str.split(":"))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError
            except (ValueError, IndexError, AttributeError):
                logger.warning(f"Invalid run_time {run_time_str}, using default 03:00")
                run_time_str = "03:00"
                hour, minute = 3, 0

            now_local = datetime.now(tz)
            check_date = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)

            # If run_time has passed today, start from tomorrow
            if check_date <= now_local:
                check_date += timedelta(days=1)

            if frequency == "daily":
                # Daily retraining - next run is tomorrow at run_time
                return check_date.astimezone(pytz.UTC)
            else:
                # Weekly retraining on specific days
                run_days = config.get("run_days", [1, 4])  # Default Mon/Thu for backward compat
                if not isinstance(run_days, list) or not all(
                    isinstance(d, int) and 0 <= d <= 6
                    for d in run_days  # type: ignore[arg-type]
                ):
                    logger.warning(f"Invalid run_days {run_days}, using default [1, 4]")
                    run_days = [1, 4]

                # Find next matching day
                days_checked = 0
                while days_checked < 8:
                    if check_date.weekday() in run_days:
                        return check_date.astimezone(pytz.UTC)
                    check_date += timedelta(days=1)
                    days_checked += 1

                # Fallback
                return check_date.astimezone(pytz.UTC)

        except Exception as e:
            logger.error(f"Failed to compute next training time: {e}")
            return datetime.now(UTC) + timedelta(days=1)

    async def _run_price_forecast_daily(self, config: dict[str, Any]) -> None:
        """Execute daily price forecast generation at 06:00.

        This runs independently of training and planner schedules to accumulate
        weather snapshots for faster model bootstrap.
        """
        from ml.price_forecast import generate_price_forecasts

        self._status.current_task = "price_forecast"
        logger.info("Starting daily price forecast generation...")

        try:
            # Run price forecast generation
            # Pass model_path=None to allow weather-only rows when no model exists
            from backend.learning import get_learning_engine

            engine = get_learning_engine()
            engine.reload_config_if_changed()

            forecasts = await generate_price_forecasts(
                config=engine.config,
                db_path=str(engine.db_path),
                model_path=None,  # Let the function check if models exist
            )

            self._status.last_price_forecast_at = datetime.now(UTC)
            logger.info(f"Daily price forecast completed: {len(forecasts)} records generated")

        except Exception as e:
            logger.error(f"Daily price forecast failed: {e}")
            # Don't mark as failed status to avoid alerting - this is non-critical

        self._status.current_task = "idle"
        # Schedule next run for tomorrow at 06:00
        self._status.next_price_forecast_at = self._compute_next_price_forecast(config)

    def _compute_next_price_forecast(self, config: dict[str, Any]) -> datetime:
        """Calculate next price forecast time at 06:00 local time."""
        import pytz

        try:
            # Load timezone from global config or default
            global_config = self._load_global_config()
            tz_str: str = global_config.get("timezone", "Europe/Stockholm")
            tz = pytz.timezone(tz_str)

            # Default to 06:00, can be configured
            run_time_str = config.get("daily_run_time", "06:00")
            try:
                hour, minute = map(int, run_time_str.split(":"))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError
            except (ValueError, IndexError, AttributeError):
                logger.warning(f"Invalid daily_run_time {run_time_str}, using default 06:00")
                run_time_str = "06:00"
                hour, minute = 6, 0

            now_local = datetime.now(tz)
            next_run = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)

            # If run_time has passed today, schedule for tomorrow
            if next_run <= now_local:
                next_run += timedelta(days=1)

            return next_run.astimezone(pytz.UTC)

        except Exception as e:
            logger.error(f"Failed to compute next price forecast time: {e}")
            # Default to tomorrow at 06:00 UTC
            return datetime.now(UTC).replace(hour=6, minute=0, second=0, microsecond=0) + timedelta(
                days=1
            )

    def _load_global_config(self) -> dict[str, Any]:
        """Load global config from config.yaml."""
        try:
            with Path("config.yaml").open() as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load global config: {e}")
            return {}

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
                cfg: dict[str, Any] = yaml.safe_load(f) or {}

            automation: dict[str, Any] = cfg.get("automation", {})
            schedule: dict[str, Any] = automation.get("schedule", {})

            return {
                "enabled": bool(automation.get("enable_scheduler", False)),
                "every_minutes": int(schedule.get("every_minutes", 60)),
                "jitter_minutes": int(schedule.get("jitter_minutes", 0)),
                "ml_training": automation.get("ml_training", {}),
                "price_forecast": cfg.get("price_forecast", {}),
            }
        except Exception as e:
            logger.warning(f"Failed to load scheduler config: {e}")
            return {
                "enabled": False,
                "every_minutes": 60,
                "jitter_minutes": 0,
                "ml_training": {"enabled": False},
                "price_forecast": {"enabled": False},
            }


# Global singleton
scheduler_service = SchedulerService()
