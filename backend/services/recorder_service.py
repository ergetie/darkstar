"""
Async Recorder Service

Background task that captures system observations every 15 minutes.
Integrated into the backend lifecycle for production-grade reliability.
"""

import asyncio
import contextlib
import logging
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from backend.learning.backfill import BackfillEngine
from backend.loads.service import LoadDisaggregator
from backend.recorder import (
    backfill_missing_prices,
    record_observation_from_current_state,
)

logger = logging.getLogger("darkstar.services.recorder")


@dataclass
class RecorderStatus:
    """Current state of the recorder service."""

    running: bool = False
    last_record_at: datetime | None = None
    last_error: str | None = None
    error_count: int = 0
    recent_errors: deque[str] | None = None  # Bounded queue of error messages

    def __post_init__(self) -> None:
        if self.recent_errors is None:
            self.recent_errors = deque(maxlen=10)


class RecorderService:
    """Async recorder service running as FastAPI background task."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._status = RecorderStatus()
        self._config: dict[str, Any] = {}
        self._disaggregator: LoadDisaggregator | None = None

    @property
    def status(self) -> RecorderStatus:
        """Get current recorder status."""
        return self._status

    async def start(self) -> None:
        """Start the recorder background loop."""
        if self._running:
            logger.warning("Recorder already running")
            return

        self._running = True
        self._status.running = True
        self._task = asyncio.create_task(self._loop(), name="recorder_loop")
        logger.info("RecorderService started")

    async def stop(self) -> None:
        """Gracefully stop the recorder."""
        self._running = False
        self._status.running = False

        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self._task, timeout=5.0)
            self._task = None

        logger.info("RecorderService stopped")

    def _load_config(self) -> dict[str, Any]:
        try:
            with Path("config.yaml").open(encoding="utf-8") as f:
                result: dict[str, Any] = yaml.safe_load(f) or {}
                return result
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return {}

    async def _record_with_retry(self) -> bool:
        """
        Record observation with retry logic.

        Waits briefly after waking to allow pending processes to complete,
        then attempts to record. If it fails, retries once more.

        This is part of the "belt and suspenders" approach to handle timestamp
        alignment between ML forecast generation and price slot boundaries:
        1. Root cause fix: ml/forward.py aligns to current 15-min boundary
        2. This retry: waits 5s after waking to let pending writes complete
        3. Defensive fallback: inputs.py interpolates small gaps

        Returns True if recording succeeded, False if all attempts failed.
        """
        # Wait 5 seconds to allow pending DB writes/ML processes to complete
        await asyncio.sleep(5)

        max_retries = 2
        for attempt in range(1, max_retries + 1):
            try:
                await record_observation_from_current_state(self._config, self._disaggregator)
                self._status.last_record_at = datetime.now(UTC)
                return True
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(
                        f"Observation recording failed (attempt {attempt}/{max_retries}): {e}. "
                        f"Retrying..."
                    )
                    await asyncio.sleep(3)  # Brief delay before retry
                else:
                    logger.error(f"Observation recording failed after {max_retries} attempts: {e}")
                    self._status.last_error = str(e)
                    self._status.error_count += 1
                    self._status.recent_errors.append(  # type: ignore[union-attr]
                        f"{datetime.now(UTC).isoformat()}: Observation gap - {e}"
                    )
                    return False
        return False

    async def _loop(self) -> None:
        """Main recorder loop."""
        logger.info("Recorder loop starting...")

        self._config = self._load_config()

        # 1. Backfill energy on startup
        try:
            backfill = BackfillEngine()
            await backfill.run()
        except Exception as e:
            logger.error(f"Energy backfill failed: {e}")

        # 2. Backfill prices on startup
        await backfill_missing_prices()

        # 3. Initialize disaggregator
        self._disaggregator = LoadDisaggregator(self._config)

        while self._running:
            try:
                # Wake on the boundary, then record the completed slot.
                await self._sleep_until_next_quarter()

                success = await self._record_with_retry()
                if not success:
                    logger.warning("Observation gap detected, will backfill on next tick")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Recorder loop error: {e}")
                self._status.last_error = str(e)
                self._status.error_count += 1
                self._status.recent_errors.append(f"{datetime.now(UTC).isoformat()}: {e}")  # type: ignore[union-attr]
                await asyncio.sleep(60)  # Back off on error

    async def _sleep_until_next_quarter(self) -> None:
        """Sleep until the next 15-minute boundary."""
        now = datetime.now(UTC)
        minute_block = (now.minute // 15) * 15
        current_slot = now.replace(minute=minute_block, second=0, microsecond=0)
        next_slot = current_slot + timedelta(minutes=15)
        sleep_seconds = max(5.0, (next_slot - now).total_seconds())
        await asyncio.sleep(sleep_seconds)


# Global singleton
recorder_service = RecorderService()
