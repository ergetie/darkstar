"""Nightly battery hindsight benchmark (read-only on observations).

At 00:10 local and once after startup, scores every finished day of the last
14 days that has no stored non-failed result for the current benchmark version, oldest
first, one solve at a time off the event loop. Results go to system_state.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

import pytz

from backend.battery_benchmark import (
    BENCHMARK_VERSION,
    base_record,
    benchmark_day,
    rows_by_local_day,
    state_key,
)
from backend.core.secrets import load_yaml
from planner.solver.adapter import config_to_kepler_config

if TYPE_CHECKING:
    from collections.abc import Callable

    from backend.learning.store import LearningStore

logger = logging.getLogger("darkstar.services.benchmark")

WINDOW_DAYS = 14
# Days of history loaded before the oldest pending day (start SoC + capacity check).
HISTORY_DAYS = 14
RUN_AT = time(0, 10)


class BenchmarkService:
    def __init__(
        self,
        config_loader: Callable[[], dict[str, Any]] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._config_loader = config_loader or (lambda: load_yaml("config.yaml") or {})
        self._now = now or (lambda: datetime.now(pytz.UTC))
        self._task: asyncio.Task[None] | None = None

    async def start(self, store: LearningStore) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(store), name="battery_benchmark")
        logger.info("BenchmarkService started")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        logger.info("BenchmarkService stopped")

    async def _loop(self, store: LearningStore) -> None:
        while True:
            try:
                await self.run_once(store)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Battery benchmark run failed")
            tz = pytz.timezone(str(self._config_loader().get("timezone", "Europe/Stockholm")))
            now = self._now().astimezone(tz)
            next_run = tz.localize(datetime.combine(now.date(), RUN_AT))
            if next_run <= now:
                next_run = tz.localize(datetime.combine(now.date() + timedelta(days=1), RUN_AT))
            await asyncio.sleep((next_run - now).total_seconds())

    async def run_once(self, store: LearningStore) -> list[date]:
        """Score pending days; returns the days processed."""
        config = config_to_kepler_config(self._config_loader())
        if config.capacity_kwh <= 0:
            return []
        tz = pytz.timezone(config.timezone_name)
        now = self._now().astimezone(tz)
        today = now.date()
        days = [today - timedelta(days=k) for k in range(WINDOW_DAYS, 0, -1)]
        stored = await store.get_system_states([state_key(d) for d in days])
        pending = [d for d in days if not _is_done(stored.get(state_key(d)))]
        if not pending:
            return []

        start = tz.localize(datetime.combine(pending[0] - timedelta(days=HISTORY_DAYS), time()))
        end = tz.localize(datetime.combine(today, time()))
        by_day = rows_by_local_day(await store.get_slot_observation_rows(start, end), tz)
        for day in pending:
            try:
                record = await asyncio.to_thread(benchmark_day, day, by_day, config, now)
            except Exception as exc:
                logger.exception("Battery benchmark failed for %s", day)
                record = base_record(day, config)
                record.update(status="failed", reason="error", solver_status=type(exc).__name__)
            await store.set_system_state(state_key(day), json.dumps(record))
            logger.info(
                "Battery benchmark %s: %s %s", day, record["status"], record.get("reason") or ""
            )
        return pending


def _is_done(raw: str | None) -> bool:
    """Stored with the current version and not failed (failed days are retried)."""
    if raw is None:
        return False
    try:
        record = json.loads(raw)
        return record.get("version") == BENCHMARK_VERSION and record.get("status") != "failed"
    except (ValueError, AttributeError):
        return False


benchmark_service = BenchmarkService()
