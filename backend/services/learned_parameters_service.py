"""Daily estimation of learned battery and inverter parameters.

Runs 5 minutes after startup and then at 00:40 local (after the nightly benchmark at 00:10).
Every error is logged and never reaches the planner, the executor or the recorder: the
planner only reads the stored values and never waits for an estimate.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any, cast

import pytz

from backend.core.secrets import load_yaml
from backend.learning import learned_parameters as lp
from backend.learning.battery_estimators import LOSS_LOOKBACK_DAYS, RTE_LOOKBACK_DAYS

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from backend.learning.store import LearningStore

logger = logging.getLogger("darkstar.services.learned_parameters")

RUN_AT = time(0, 40)
STARTUP_DELAY = timedelta(minutes=5)
# One extra day for the SoC anchor before the first whole day, one for the partial first day.
HISTORY_DAYS = max(RTE_LOOKBACK_DAYS, LOSS_LOOKBACK_DAYS) + 2


def next_run_time(now: datetime, tz: Any) -> datetime:
    """The next local ``RUN_AT`` strictly after ``now`` (timezone-aware)."""
    local = now.astimezone(tz)
    candidate = tz.localize(datetime.combine(local.date(), RUN_AT))
    if candidate <= local:
        candidate = tz.localize(datetime.combine(local.date() + timedelta(days=1), RUN_AT))
    return candidate


async def executor_notifier(title: str, message: str) -> bool:
    """Deliver through the executor's notification service; False when it is unavailable."""
    from backend.api.routers.executor import get_executor_instance

    executor = get_executor_instance()
    if executor is None:
        return False
    return bool(await executor.send_notification(title, message))


class LearnedParametersService:
    def __init__(
        self,
        config_loader: Callable[[], dict[str, Any]] | None = None,
        now: Callable[[], datetime] | None = None,
        notifier: Callable[[str, str], Awaitable[bool]] | None = None,
        startup_delay: timedelta = STARTUP_DELAY,
    ) -> None:
        self._config_loader = config_loader or (lambda: load_yaml("config.yaml") or {})
        self._now = now or (lambda: datetime.now(pytz.UTC))
        self._notifier = notifier or executor_notifier
        self._startup_delay = startup_delay
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(self, store: LearningStore) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(store), name="learned_parameters")
        logger.info("LearnedParametersService started")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        logger.info("LearnedParametersService stopped")

    async def _loop(self, store: LearningStore) -> None:
        await asyncio.sleep(self._startup_delay.total_seconds())
        while True:
            try:
                await self.run_once(store)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Learned parameter run failed")
            try:
                tz = pytz.timezone(str(self._config_loader().get("timezone", "Europe/Stockholm")))
            except Exception:
                logger.exception("Learned parameter scheduling fell back to the default timezone")
                tz = pytz.timezone("Europe/Stockholm")
            now = self._now()
            await asyncio.sleep((next_run_time(now, tz) - now.astimezone(tz)).total_seconds())

    async def run_once(self, store: LearningStore) -> list[lp.AppliedChange]:
        """Estimate and apply once; returns the changes. Serialised with other runs."""
        async with self._lock:
            config = self._config_loader()
            learning: Any = config.get("learning")
            tz = pytz.timezone(str(config.get("timezone", "Europe/Stockholm")))
            now = self._now().astimezone(tz)
            if (
                isinstance(learning, dict)
                and cast("dict[str, Any]", learning).get("enable") is False
            ):
                # No new estimates, but stale values must still expire visibly (history,
                # notification) and undelivered notifications must still be retried.
                logger.debug("Learning is disabled; learned parameters are not estimated")
                return await lp.run_once(
                    lp.LearnedParameterStore(store),
                    [],
                    config,
                    now,
                    self._notifier,
                    run_estimators=False,
                )
            start = tz.localize(datetime.combine(now.date() - timedelta(days=HISTORY_DAYS), time()))
            rows = await store.get_slot_observation_rows(start, now)
            sensor_values = await store.get_inverter_loss_values(start, now)
            changes = await lp.run_once(
                lp.LearnedParameterStore(store), rows, config, now, self._notifier, sensor_values
            )
            logger.info("Learned parameters: %d change(s) from %d slots", len(changes), len(rows))
            return changes


learned_parameters_service = LearnedParametersService()
