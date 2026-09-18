"""
Async Planner Service

Wraps the blocking PlannerPipeline in an async interface suitable
for running inside the FastAPI process without blocking the event loop.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.core.cache import cache
from backend.core.websockets import ws_manager
from planner.errors import (
    PlannerError,
    PlannerErrorCode,
    is_config_blocking,
    is_transient,
    is_warning_only,
)

logger = logging.getLogger("darkstar.services.planner")

_BACKOFF_STEPS = [60, 120, 240, 300]  # seconds, last value is cap
_SUSPENSION_CEILING_S = 1800


@dataclass
class PlannerResult:
    """Result of a planner execution."""

    success: bool
    planned_at: datetime
    slot_count: int = 0
    error: str | None = None
    duration_ms: float = 0
    error_code: str | None = None
    error_details: dict[str, Any] | None = None
    fix_hint: str | None = None


class PlannerService:
    """Async planner service for in-process execution."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._current_phase: str | None = None
        self._planner_start_time: datetime | None = None

        # Retry policy state (in-memory only, always resets on restart).
        # On startup, _retry_suspended=False so the first run always proceeds.
        self._last_error_code: PlannerErrorCode | None = None
        self._last_error_at: datetime | None = None
        self._last_error_details: dict[str, Any] | None = None
        self._next_retry_at: datetime | None = None
        self._consecutive_failures: int = 0
        self._retry_suspended: bool = False
        self._suspended_since: datetime | None = None

    @property
    def retry_suspended(self) -> bool:
        """Whether automatic retries are suspended."""
        return self._retry_suspended

    @property
    def next_retry_at(self) -> datetime | None:
        """Timestamp of next scheduled retry."""
        return self._next_retry_at

    @property
    def suspension_expired(self) -> bool:
        """Whether the active retry suspension has reached its retry ceiling."""
        return bool(
            self._retry_suspended
            and self._suspended_since is not None
            and (datetime.now(UTC) - self._suspended_since).total_seconds() >= _SUSPENSION_CEILING_S
        )

    @property
    def last_error_code(self) -> PlannerErrorCode | None:
        """Most recent planner error code."""
        return self._last_error_code

    @property
    def last_error_details(self) -> dict[str, Any] | None:
        """Details of most recent planner error."""
        return self._last_error_details

    @property
    def retry_in_s(self) -> int | None:
        """Seconds until next retry, or None if suspended."""
        if self._retry_suspended:
            return None
        if self._next_retry_at is None:
            return None
        remaining = (self._next_retry_at - datetime.now(UTC)).total_seconds()
        return max(0, int(remaining))

    def _apply_retry_policy(self, code: PlannerErrorCode) -> None:
        now = datetime.now(UTC)
        if is_warning_only(code):
            # Warning-only: treat as success for retry purposes
            return
        if is_config_blocking(code):
            self._retry_suspended = True
            self._suspended_since = now
            self._next_retry_at = None
        elif is_transient(code):
            step_index = min(self._consecutive_failures - 1, len(_BACKOFF_STEPS) - 1)
            delay = _BACKOFF_STEPS[max(0, step_index)]
            self._next_retry_at = now + timedelta(seconds=delay)
        else:
            # Invariant/state errors: normal 60s cadence
            self._next_retry_at = now + timedelta(seconds=60)

    def clear_retry_suspension(self) -> None:
        """Clear retry suspension and schedule an immediate retry."""
        self._retry_suspended = False
        self._suspended_since = None
        self._next_retry_at = datetime.now(UTC)

    async def _emit_progress(self, phase: str) -> None:
        """Emit progress event via WebSocket."""
        self._current_phase = phase

        elapsed_ms = 0.0
        if self._planner_start_time:
            # naive by design: elapsed-duration only, never crosses a module boundary
            elapsed_ms = (datetime.now() - self._planner_start_time).total_seconds() * 1000

        try:
            await ws_manager.emit(
                "planner_progress",
                {
                    "phase": phase,
                    "elapsed_ms": elapsed_ms,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            logger.debug(f"Planner progress: {phase} ({elapsed_ms:.0f}ms)")
        except Exception as e:
            logger.warning(f"Failed to emit progress for phase '{phase}': {e}")

    def get_status(self) -> dict[str, Any]:
        """Get current planner status (for HTTP fallback)."""
        if not self._current_phase:
            return {"phase": "idle", "elapsed_ms": 0, "is_running": False}

        elapsed_ms = 0.0
        if self._planner_start_time:
            # naive by design: elapsed-duration only, never crosses a module boundary
            elapsed_ms = (datetime.now() - self._planner_start_time).total_seconds() * 1000

        return {
            "phase": self._current_phase,
            "elapsed_ms": elapsed_ms,
            "is_running": self._lock.locked(),
        }

    async def run_once(
        self,
        ev_plugged_in_override: bool | None = None,
        ev_charger_id_override: str | None = None,
    ) -> PlannerResult:
        """
        Run the planner asynchronously.
        Handles cache invalidation and WebSocket notification automatically.

        Uses a lock to prevent concurrent planner executions.

        Args:
            ev_plugged_in_override: If True, passes plugged-in state to avoid REST race
            ev_charger_id_override: Charger ID to apply the plug state override to (Task 7.3)
        """
        # Prevent concurrent runs
        if self._lock.locked():
            logger.warning("Planner already running, skipping concurrent request")
            return PlannerResult(
                success=False,
                planned_at=datetime.now(UTC),
                error="Planner already running",
            )

        async with self._lock:
            # naive by design: elapsed-duration only, never crosses a module boundary
            start = datetime.now()
            planned_at = datetime.now(UTC)
            self._planner_start_time = start

            try:
                await self._emit_progress("fetching_inputs")

                from bin.run_planner import main as run_planner_main

                exit_code = await run_planner_main(
                    progress_callback=self._emit_progress,
                    ev_plugged_in_override=ev_plugged_in_override,
                    ev_charger_id_override=ev_charger_id_override,
                )

                if exit_code == 0:
                    slot_count = self._count_schedule_slots()
                    result = PlannerResult(
                        success=True,
                        planned_at=planned_at,
                        slot_count=slot_count,
                    )
                else:
                    result = PlannerResult(
                        success=False,
                        planned_at=planned_at,
                        error=f"Planner exited with code {exit_code}",
                    )

                # naive by design: elapsed-duration only, never crosses a module boundary
                result.duration_ms = (datetime.now() - start).total_seconds() * 1000

                if result.success:
                    await self._emit_progress("complete")
                    self._on_success()
                    await self._notify_success(result)
                else:
                    self._consecutive_failures += 1
                    await self._notify_error(result)

                self._current_phase = None
                self._planner_start_time = None

                return result

            except PlannerError as e:
                logger.exception("Planner execution failed with typed error: %s", e.code)
                self._consecutive_failures += 1
                self._last_error_code = e.code
                self._last_error_at = datetime.now(UTC)
                self._last_error_details = e.details or {}
                self._apply_retry_policy(e.code)

                # naive by design: elapsed-duration only, never crosses a module boundary
                duration_ms = (datetime.now() - start).total_seconds() * 1000
                result = PlannerResult(
                    success=False,
                    planned_at=planned_at,
                    error=e.message,
                    duration_ms=duration_ms,
                    error_code=e.code.value,
                    error_details=e.details,
                    fix_hint=e.fix_hint,
                )
                await self._notify_error(result)
                await self._emit_progress("failed")

                self._current_phase = None
                self._planner_start_time = None

                return result

            except Exception as e:
                logger.exception("Planner execution failed")
                self._consecutive_failures += 1
                self._last_error_code = PlannerErrorCode.UNKNOWN
                self._last_error_at = datetime.now(UTC)
                self._last_error_details = {"exception": str(e)}
                self._apply_retry_policy(PlannerErrorCode.UNKNOWN)

                # naive by design: elapsed-duration only, never crosses a module boundary
                duration_ms = (datetime.now() - start).total_seconds() * 1000
                result = PlannerResult(
                    success=False,
                    planned_at=planned_at,
                    error=f"{type(e).__name__}: {e!s}",
                    duration_ms=duration_ms,
                    error_code=PlannerErrorCode.UNKNOWN.value,
                    error_details={"exception": str(e)},
                )
                await self._notify_error(result)
                await self._emit_progress("failed")

                self._current_phase = None
                self._planner_start_time = None

                return result

    def _on_success(self) -> None:
        self._consecutive_failures = 0
        self._retry_suspended = False
        self._suspended_since = None
        self._last_error_code = None
        self._last_error_at = None
        self._last_error_details = None
        self._next_retry_at = None

    def _count_schedule_slots(self) -> int:
        """Count slots in schedule.json for metadata."""
        import json

        try:
            with Path("data/schedule.json").open() as f:
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
                    "code": result.error_code,
                    "details": result.error_details,
                },
            )
            logger.error("Planner failed: %s", result.error)
        except Exception as e:
            logger.warning(f"Failed to notify error: {e}")


# Global singleton
planner_service = PlannerService()
