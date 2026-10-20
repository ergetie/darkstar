"""Bounded retry for transient Open-Meteo failures (PV and weather fetches).

Open-Meteo occasionally returns short-lived 5xx/429 responses or drops
connections. A small, fixed backoff absorbs these blips within a single
planner run; persistent or permanent errors are re-raised unchanged so the
caller's existing fallback and error reporting run as before.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

import aiohttp
import requests
from open_meteo_solar_forecast.exceptions import (
    OpenMeteoSolarForecastConnectionError,
    OpenMeteoSolarForecastRatelimitError,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
# Wait before attempt 2 and attempt 3; total retry wait is 6 s (< 10 s cap).
BACKOFF_S: tuple[float, ...] = (2.0, 4.0)

_LOG_FMT = "Open-Meteo %s failed (attempt %d/%d): %s; retrying in %.0fs"


def _is_transient_status(status: int | None) -> bool:
    return status is not None and (status >= 500 or status == 429)


def is_transient_pv_error(exc: BaseException) -> bool:
    """Classify an `open_meteo_solar_forecast` / aiohttp error as transient."""
    # Ratelimit subclasses RequestError (permanent), so check it explicitly first.
    if isinstance(
        exc, OpenMeteoSolarForecastRatelimitError | OpenMeteoSolarForecastConnectionError
    ):
        return True
    if isinstance(exc, aiohttp.ClientResponseError):
        return _is_transient_status(exc.status)
    return isinstance(exc, aiohttp.ClientConnectionError | asyncio.TimeoutError)


def is_transient_http_error(exc: BaseException) -> bool:
    """Classify a `requests` error as transient."""
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        return _is_transient_status(response.status_code if response is not None else None)
    return isinstance(exc, requests.ConnectionError | requests.Timeout)


def _delay_for(attempt: int) -> float:
    return BACKOFF_S[min(attempt - 1, len(BACKOFF_S) - 1)]


async def retry_async[T](
    fn: Callable[[], Awaitable[T]],
    *,
    label: str,
    is_transient: Callable[[BaseException], bool],
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> T:
    """Await `fn()` with bounded retries on transient errors; re-raise the last error."""
    attempt = 1
    while True:
        try:
            return await fn()
        except Exception as exc:
            if attempt >= MAX_ATTEMPTS or not is_transient(exc):
                raise
            delay = _delay_for(attempt)
            logger.warning(_LOG_FMT, label, attempt, MAX_ATTEMPTS, exc, delay)
        await sleep(delay)
        attempt += 1


def retry_sync[T](
    fn: Callable[[], T],
    *,
    label: str,
    is_transient: Callable[[BaseException], bool],
    sleep: Callable[[float], object] = time.sleep,
) -> T:
    """Call `fn()` with bounded retries on transient errors; re-raise the last error.

    Blocks the calling thread while waiting; callers on the event loop must run
    this via `asyncio.to_thread`.
    """
    attempt = 1
    while True:
        try:
            return fn()
        except Exception as exc:
            if attempt >= MAX_ATTEMPTS or not is_transient(exc):
                raise
            delay = _delay_for(attempt)
            logger.warning(_LOG_FMT, label, attempt, MAX_ATTEMPTS, exc, delay)
        sleep(delay)
        attempt += 1
