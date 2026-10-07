"""Failure-isolated daily installation statistics sender."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx

from backend.core.secrets import load_yaml
from backend.services.installation_stats_contract import (
    build_installation_stats_payload,
    classify_release_channel,
    effective_installation_stats,
    is_valid_telemetry_endpoint,
)
from backend.services.installation_stats_state import (
    InstallationStatsState,
    InstallationStatsStateError,
)

logger = logging.getLogger("darkstar.installation_stats")
CONFIG_CHECK_SECONDS = 30.0
HTTP_TIMEOUT_SECONDS = 5.0
FAILURE_RETRY_SECONDS = 5 * 60
SUCCESS_INTERVAL_SECONDS = 24 * 60 * 60
SUCCESS_JITTER_SECONDS = 15 * 60


class InstallationStatsService:
    """Manage a single cancellable sender task and its HTTP client."""

    def __init__(
        self,
        *,
        data_dir: str | Path = "data",
        config_loader: Callable[[], object] | None = None,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        now: Callable[[], datetime] | None = None,
        randint: Callable[[int, int], int] | None = None,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._config_loader = config_loader or (lambda: load_yaml("config.yaml") or {})
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(
                timeout=httpx.Timeout(HTTP_TIMEOUT_SECONDS),
                verify=True,
                follow_redirects=False,
            )
        )
        self._now = now or (lambda: datetime.now(UTC))
        self._randint = randint or random.randint
        self._event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._client: httpx.AsyncClient | None = None
        self._stopping = False

    async def start(self) -> None:
        """Start reporting without allowing telemetry failures to fail lifespan."""
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        try:
            self._client = self._client_factory()
            self._task = asyncio.create_task(self._run_guarded(), name="installation-stats")
        except Exception as exc:
            self._client = None
            logger.warning("Installation statistics sender unavailable (%s)", type(exc).__name__)

    async def _run_guarded(self) -> None:
        try:
            await self._run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Installation statistics sender stopped (%s)", type(exc).__name__)

    def notify_config_changed(self) -> None:
        """Wake the sender after a successful settings save."""
        self._event.set()

    async def stop(self) -> None:
        """Cancel waits/in-flight requests and close the HTTP client promptly."""
        self._stopping = True
        self._event.set()
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning(
                    "Installation statistics sender stopped with an error (%s)", type(exc).__name__
                )
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.aclose()
            except Exception as exc:
                logger.warning(
                    "Installation statistics client close failed (%s)", type(exc).__name__
                )

    async def _run(self) -> None:
        channel = classify_release_channel()
        state = InstallationStatsState(self._data_dir / f"installation_stats.{channel}.json")
        state_loaded = False
        next_due: datetime | None = None
        state_error_reported = False
        config_error_reported = False

        while not self._stopping:
            # Clear before reading so a concurrent save either appears in the
            # read or leaves the event set to wake the next wait.
            self._event.clear()
            try:
                config = await asyncio.to_thread(self._config_loader)
                if not isinstance(config, Mapping):
                    raise ValueError("configuration root is not an object")
                settings = effective_installation_stats(cast("Mapping[str, Any]", config))
                enabled = settings.get("enabled")
                endpoint = settings.get("endpoint")
                valid_config = isinstance(enabled, bool) and is_valid_telemetry_endpoint(endpoint)
                if not valid_config:
                    if not config_error_reported:
                        logger.warning(
                            "Installation statistics config is invalid; reporting is paused"
                        )
                        config_error_reported = True
                    await self._wait(CONFIG_CHECK_SECONDS)
                    continue
                config_error_reported = False
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not config_error_reported:
                    logger.warning(
                        "Installation statistics config unavailable (%s)", type(exc).__name__
                    )
                    config_error_reported = True
                await self._wait(CONFIG_CHECK_SECONDS)
                continue

            if not enabled:
                await self._wait(CONFIG_CHECK_SECONDS)
                continue

            if not state_loaded:
                try:
                    await asyncio.to_thread(state.load)
                    state_loaded = True
                    state_error_reported = False
                except InstallationStatsStateError as exc:
                    if not state_error_reported:
                        logger.warning("Installation statistics state unavailable (%s)", str(exc))
                        state_error_reported = True
                    await self._wait(CONFIG_CHECK_SECONDS)
                    continue

            now = self._now().astimezone(UTC)
            if next_due is None:
                if state.last_attempt is None:
                    next_due = now
                elif state.last_success is None or state.last_attempt > state.last_success:
                    # Legacy attempts have no success marker and are treated as
                    # unconfirmed. A failed dispatch is retried from its attempt.
                    next_due = state.last_attempt + timedelta(seconds=FAILURE_RETRY_SECONDS)
                elif state.next_attempt_due is not None:
                    next_due = state.next_attempt_due
                else:
                    # Only possible for a state written by an intermediate
                    # version; persist the chosen jitter once for restart safety.
                    next_due = state.last_success + timedelta(
                        seconds=SUCCESS_INTERVAL_SECONDS + self._randint(0, SUCCESS_JITTER_SECONDS)
                    )
                    try:
                        await asyncio.to_thread(state.record_success, state.last_success, next_due)
                    except InstallationStatsStateError as exc:
                        logger.warning(
                            "Installation statistics schedule was not saved (%s)", str(exc)
                        )
                        next_due = now + timedelta(seconds=FAILURE_RETRY_SECONDS)

            wait_seconds = max(0.0, (next_due - now).total_seconds())
            if wait_seconds > 0:
                await self._wait(min(CONFIG_CHECK_SECONDS, wait_seconds))
                continue

            # Read again immediately before committing the attempt and sending.
            try:
                latest = await asyncio.to_thread(self._config_loader)
                if not isinstance(latest, Mapping):
                    raise ValueError("configuration root is not an object")
                latest_config = cast("Mapping[str, Any]", latest)
                latest_settings = effective_installation_stats(latest_config)
                latest_endpoint = latest_settings.get("endpoint")
                if latest_settings.get("enabled") is not True or not is_valid_telemetry_endpoint(
                    latest_endpoint
                ):
                    next_due = None
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Installation statistics config recheck failed (%s)", type(exc).__name__
                )
                await self._wait(CONFIG_CHECK_SECONDS)
                continue

            attempted_at = self._now().astimezone(UTC)
            try:
                await asyncio.to_thread(state.record_attempt, attempted_at)
            except InstallationStatsStateError as exc:
                logger.warning("Installation statistics attempt was skipped (%s)", str(exc))
                # Do not retry disk writes every config poll when state storage
                # is unavailable. No request is sent without a durable attempt.
                next_due = attempted_at + timedelta(seconds=FAILURE_RETRY_SECONDS)
                await self._wait(min(CONFIG_CHECK_SECONDS, FAILURE_RETRY_SECONDS))
                continue

            if self._client is None or state.installation_id is None:
                logger.warning("Installation statistics HTTP client is unavailable")
                next_due = attempted_at + timedelta(seconds=FAILURE_RETRY_SECONDS)
                await self._wait(CONFIG_CHECK_SECONDS)
                continue

            # Persisting the attempt yields to other tasks. A settings save may
            # disable reporting or change the endpoint during that write, so
            # read again before dispatch and suppress a concurrent notification.
            self._event.clear()
            try:
                latest = await asyncio.to_thread(self._config_loader)
                if not isinstance(latest, Mapping):
                    raise ValueError("configuration root is not an object")
                latest_config = cast("Mapping[str, Any]", latest)
                latest_settings = effective_installation_stats(latest_config)
                latest_endpoint = latest_settings.get("endpoint")
                if (
                    self._event.is_set()
                    or latest_settings.get("enabled") is not True
                    or not is_valid_telemetry_endpoint(latest_endpoint)
                ):
                    next_due = None
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Installation statistics final config recheck failed (%s)", type(exc).__name__
                )
                next_due = None
                await self._wait(CONFIG_CHECK_SECONDS)
                continue

            payload = build_installation_stats_payload(latest_config, state.installation_id)
            succeeded = False
            try:
                async with asyncio.timeout(HTTP_TIMEOUT_SECONDS):
                    response = await self._client.post(str(latest_endpoint), json=payload)
                succeeded = response.status_code == 204
                if not succeeded:
                    logger.info(
                        "Installation statistics attempt returned HTTP %d", response.status_code
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.info("Installation statistics attempt failed (%s)", type(exc).__name__)

            if succeeded:
                confirmed_at = self._now().astimezone(UTC)
                next_due = confirmed_at + timedelta(
                    seconds=SUCCESS_INTERVAL_SECONDS + self._randint(0, SUCCESS_JITTER_SECONDS)
                )
                try:
                    await asyncio.to_thread(state.record_success, confirmed_at, next_due)
                except InstallationStatsStateError as exc:
                    # The durable attempt remains newer than the last success,
                    # so a restart will retry in five minutes as well.
                    logger.warning("Installation statistics success was not saved (%s)", str(exc))
                    next_due = attempted_at + timedelta(seconds=FAILURE_RETRY_SECONDS)
            else:
                next_due = attempted_at + timedelta(seconds=FAILURE_RETRY_SECONDS)

    async def _wait(self, seconds: float) -> None:
        if self._stopping:
            return
        with suppress(TimeoutError):
            await asyncio.wait_for(self._event.wait(), timeout=max(0.0, seconds))


installation_stats_service = InstallationStatsService()
