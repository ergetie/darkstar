"""Background database maintenance: batched retention pruning and incremental vacuum."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from backend.db_safety import RetentionConfig, incremental_vacuum, load_retention, prune

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("darkstar.db_maintenance")

LAST_RUN_KEY = "db_maintenance_last_run"
FIRST_CHECK_SECONDS = 10 * 60
CHECK_INTERVAL_SECONDS = 60 * 60
RUN_INTERVAL = timedelta(hours=24)


class _StateStore(Protocol):
    async def get_system_state(self, key: str) -> str | None: ...

    async def set_system_state(self, key: str, value: str) -> None: ...


class DbMaintenanceService:
    """Own one cancellable task that prunes and compacts the database once a day.

    Failures are logged and swallowed; a run is only recorded as done when both the
    prune and the incremental vacuum finished, so a locked database is retried at the
    next hourly check.
    """

    def __init__(
        self,
        *,
        retention_loader: Callable[[], RetentionConfig] = load_retention,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], object] | None = None,
    ) -> None:
        self._retention_loader = retention_loader
        self._now = now or (lambda: datetime.now(UTC))
        self._sleep = sleep or asyncio.sleep
        self._task: asyncio.Task[None] | None = None

    async def start(self, store: _StateStore, db_path: str | Path) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(store, Path(db_path)), name="db_maintenance")
        logger.info("DbMaintenanceService started")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        logger.info("DbMaintenanceService stopped")

    async def _loop(self, store: _StateStore, db_path: Path) -> None:
        await self._pause(FIRST_CHECK_SECONDS)
        while True:
            await self.run_if_due(store, db_path)
            await self._pause(CHECK_INTERVAL_SECONDS)

    async def _pause(self, seconds: float) -> None:
        result = self._sleep(seconds)
        if asyncio.iscoroutine(result) or isinstance(result, asyncio.Future):
            await result

    async def run_if_due(self, store: _StateStore, db_path: Path) -> bool:
        """Run maintenance when the last success is missing or 24 h old; never raises."""
        try:
            if not await self._is_due(store):
                return False
            summary = await asyncio.to_thread(self._maintain, db_path)
            await store.set_system_state(LAST_RUN_KEY, self._now().astimezone(UTC).isoformat())
            logger.info("Database maintenance finished: %s", summary)
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Database maintenance failed, retrying at the next check: %s", exc)
            return False

    async def _is_due(self, store: _StateStore) -> bool:
        raw = await store.get_system_state(LAST_RUN_KEY)
        if not raw:
            return True
        try:
            last = datetime.fromisoformat(raw)
        except ValueError:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return self._now() - last >= RUN_INTERVAL

    def _maintain(self, db_path: Path) -> str:
        deleted = prune(db_path, self._retention_loader(), now=self._now())
        freed = incremental_vacuum(db_path)
        rows = ", ".join(f"{table}={count}" for table, count in deleted.items() if count) or "none"
        return f"deleted rows: {rows}; pages returned: {freed}"


db_maintenance_service = DbMaintenanceService()
