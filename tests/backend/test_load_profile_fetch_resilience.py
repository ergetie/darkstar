"""load-profile-fetch-resilience: retry, partial window, last good profile, cooldown.

Time is simulated: ``_monotonic`` and the history retry sleep are patched onto a fake
clock, and the fake Home Assistant advances it by the read timeout of a stalled request.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytz

from backend.core import ha_client
from backend.core.ha_client import (
    _is_transient_history_error,
    get_load_profile_from_ha,
    get_power_history_batch,
)
from backend.health import (
    HealthChecker,
    clear_load_forecast_status,
    get_load_forecast_status,
    set_load_forecast_status,
)

FIXED_NOW = datetime(2026, 9, 20, 12, 0, tzinfo=pytz.UTC)
ENTITY = "sensor.inverter_load_power"
CONFIG = {"timezone": "Europe/Stockholm", "input_sensors": {"load_power": ENTITY}}
SYNTHETIC_CONFIG = {
    "timezone": "Europe/Stockholm",
    "input_sensors": {"load_power": ENTITY, "synthetic_daily_load_kwh": 20},
}
WINDOW_START = FIXED_NOW - timedelta(days=7)
HOUR = 3600


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return FIXED_NOW if tz is None else FIXED_NOW.astimezone(tz)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def advance(self, seconds: float) -> None:
        self.now += seconds

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.now += delay


@pytest.fixture(autouse=True)
def clock():
    fake = _Clock()
    with (
        patch("backend.core.ha_client.datetime", _FrozenDatetime),
        patch("backend.core.ha_client._monotonic", lambda: fake.now),
        patch("backend.core.ha_client._history_sleep", fake.sleep),
    ):
        yield fake


@pytest.fixture(autouse=True)
def _status():
    clear_load_forecast_status()
    yield
    clear_load_forecast_status()


def _state(value, ts: datetime) -> dict:
    return {
        "entity_id": ENTITY,
        "state": str(value),
        "last_changed": ts.isoformat(),
        "attributes": {"unit_of_measurement": "kW"},
    }


def _daily(values: dict[int, object]) -> list[tuple[datetime, object]]:
    """A UTC time-of-day pattern (``{second_of_day: value}``) repeated on every day."""
    midnight = datetime(2026, 9, 20, tzinfo=pytz.UTC)
    return [
        (midnight - timedelta(days=day) + timedelta(seconds=sec), value)
        for day in range(-1, 9)
        for sec, value in values.items()
    ]


# A non-flat reference: 2 kW in the first half of the UTC day, 1 kW in the second.
PATTERN = _daily({0: 2.0, 12 * HOUR: 1.0})


class _FakeHA:
    """History endpoint over ``(timestamp, value)`` points with scripted failures.

    ``fail(day, attempt)`` gets the 0-based day chunk and its 1-based attempt number and
    returns an exception to raise (``httpx.HTTPStatusError`` is raised by the response)
    or None. A ``ReadTimeout`` advances the clock by the request's read timeout.
    """

    def __init__(
        self,
        points: list[tuple[datetime, object]] | None = None,
        *,
        clock: _Clock,
        fail: Callable[[int, int], Exception | None] | None = None,
        yield_to_loop: bool = False,
    ) -> None:
        self.points = sorted(points if points is not None else PATTERN, key=lambda p: p[0])
        self.clock = clock
        self.fail = fail
        self.yield_to_loop = yield_to_loop
        self.requests: list[tuple[datetime, datetime]] = []
        self.timeouts: list[object] = []
        self.attempts: dict[int, int] = {}
        self.client = MagicMock()
        self.client.get = AsyncMock(side_effect=self._get)

    async def _get(self, api_url, headers=None, params=None, timeout=None):
        if self.yield_to_loop:
            await asyncio.sleep(0)
        start = datetime.fromisoformat(api_url.rsplit("/", 1)[1])
        end = datetime.fromisoformat(params["end_time"])
        self.requests.append((start, end))
        self.timeouts.append(timeout)
        day = round((start - WINDOW_START).total_seconds() / 86400)
        self.attempts[day] = self.attempts.get(day, 0) + 1
        response = MagicMock()
        error = self.fail(day, self.attempts[day]) if self.fail else None
        if isinstance(error, httpx.ReadTimeout):
            read = timeout.read if isinstance(timeout, httpx.Timeout) else timeout
            self.clock.advance(read)
        if isinstance(error, httpx.HTTPStatusError):
            response.raise_for_status = MagicMock(side_effect=error)
            return response
        if error is not None:
            raise error
        held = [p for p in self.points if p[0] <= start]
        states = [_state(held[-1][1], start)] if held else []
        states += [_state(v, t) for t, v in self.points if start < t < end]
        response.raise_for_status = MagicMock()
        response.json.return_value = [states] if states else []
        return response


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "http://homeassistant:8123/api/history")
    return httpx.HTTPStatusError(
        str(code), request=request, response=httpx.Response(code, request=request)
    )


@contextlib.contextmanager
def _patched_ha(fake: _FakeHA):
    with (
        patch("backend.core.ha_client.get_ha_http_client", return_value=fake.client),
        patch(
            "backend.core.secrets.load_home_assistant_config",
            return_value={"url": "http://homeassistant:8123", "token": "test_token"},
        ),
    ):
        yield


async def _call(fake: _FakeHA, config: dict | None = None, **kwargs) -> list[float]:
    with _patched_ha(fake):
        return await get_load_profile_from_ha(config or CONFIG, **kwargs)


async def _call_concurrently(fake: _FakeHA, count: int) -> list[list[float]]:
    # One patch context around all callers: overlapping per-call ``patch`` contexts exit
    # out of order and restore a mock as the "original", leaking it into later tests.
    with _patched_ha(fake):
        return await asyncio.gather(*[get_load_profile_from_ha(CONFIG) for _ in range(count)])


def _fail_days(days: set[int], error=httpx.ConnectError("refused")):
    return lambda day, _attempt: error if day in days else None


def _fail_all(error=httpx.ConnectError("refused")):
    return lambda _day, _attempt: error


# ---- classifier ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "transient"),
    [
        (httpx.ReadTimeout(""), True),
        (httpx.ConnectTimeout(""), True),
        (httpx.PoolTimeout(""), True),
        (httpx.ConnectError("refused"), True),
        (httpx.ReadError("reset"), True),
        (httpx.RemoteProtocolError("closed"), True),
        (_status_error(500), True),
        (_status_error(503), True),
        (_status_error(429), True),
        (_status_error(400), False),
        (_status_error(401), False),
        (_status_error(404), False),
        (ValueError("bad json"), False),
    ],
)
def test_history_error_classification(exc, transient):
    assert _is_transient_history_error(exc) is transient


# ---- get_power_history_batch ---------------------------------------------------


class TestHistoryBatchRetry:
    async def _batch(self, fake: _FakeHA, **kwargs):
        with (
            patch("backend.core.ha_client.get_ha_http_client", return_value=fake.client),
            patch(
                "backend.core.secrets.load_home_assistant_config",
                return_value={"url": "http://homeassistant:8123", "token": "test_token"},
            ),
        ):
            return await get_power_history_batch(
                [ENTITY], WINDOW_START, WINDOW_START + timedelta(days=1), **kwargs
            )

    async def test_default_is_one_attempt(self, clock):
        fake = _FakeHA(clock=clock, fail=_fail_all(httpx.ReadTimeout("")))
        assert await self._batch(fake) is None
        assert fake.client.get.await_count == 1
        assert clock.sleeps == []

    async def test_default_timeout_is_unchanged(self, clock):
        fake = _FakeHA(clock=clock)
        await self._batch(fake)
        assert fake.timeouts == [12.0]

    async def test_opt_in_attempts_retry_transient_with_backoff(self, clock):
        fake = _FakeHA(clock=clock, fail=_fail_all(httpx.ReadTimeout("")))
        assert await self._batch(fake, attempts=3) is None
        assert fake.client.get.await_count == 3
        assert clock.sleeps == [1.0, 3.0]

    async def test_permanent_error_is_not_retried(self, clock):
        fake = _FakeHA(clock=clock, fail=_fail_all(_status_error(401)))
        assert await self._batch(fake, attempts=3) is None
        assert fake.client.get.await_count == 1

    async def test_read_timeout_log_names_the_exception_type(self, clock, caplog):
        fake = _FakeHA(clock=clock, fail=_fail_all(httpx.ReadTimeout("")))
        with caplog.at_level(logging.WARNING, logger="darkstar.core.ha_client"):
            await self._batch(fake)
        line = next(
            r.getMessage() for r in caplog.records if "get_power_history_batch" in r.getMessage()
        )
        assert "ReadTimeout" in line
        assert not line.rstrip().endswith(":")

    async def test_deadline_caps_the_attempt_timeout_and_stops_retries(self, clock):
        fake = _FakeHA(clock=clock, fail=_fail_all(httpx.ReadTimeout("")))
        deadline = clock.now + 25.0
        await self._batch(
            fake, timeout=httpx.Timeout(20.0, connect=5.0), attempts=3, deadline=deadline
        )
        assert [t.read for t in fake.timeouts] == [20.0, pytest.approx(4.0)]
        assert clock.now <= deadline + 1e-9


# ---- fetch retry in the profile build -------------------------------------------


async def _reference(clock) -> list[float]:
    profile = await _call(_FakeHA(clock=clock))
    ha_client.reset_load_profile_state()
    clear_load_forecast_status()
    return profile


class TestChunkRetry:
    async def test_timeout_once_then_success_gives_full_profile(self, clock):
        reference = await _reference(clock)
        fake = _FakeHA(
            clock=clock,
            fail=lambda day, attempt: httpx.ReadTimeout("") if day == 3 and attempt == 1 else None,
        )
        profile = await _call(fake)
        assert profile == pytest.approx(reference)
        assert len(fake.requests) == 8
        assert get_load_forecast_status()["status"] == "ok"

    async def test_permanent_401_is_attempted_once_per_chunk(self, clock):
        fake = _FakeHA(clock=clock, fail=_fail_all(_status_error(401)))
        profile = await _call(fake)
        assert fake.attempts == {0: 1, 1: 1}
        assert profile == [0.5] * 96

    async def test_requests_use_connect_and_read_timeouts(self, clock):
        fake = _FakeHA(clock=clock)
        await _call(fake)
        timeout = fake.timeouts[0]
        assert isinstance(timeout, httpx.Timeout)
        assert (timeout.connect, timeout.read) == (5.0, 20.0)

    async def test_stalled_ha_stops_at_the_deadline(self, clock):
        start = clock.now
        fake = _FakeHA(clock=clock, fail=_fail_all(httpx.ReadTimeout("")))
        profile = await _call(fake)
        assert clock.now - start <= 60.0 + 1e-9
        assert profile == [0.5] * 96
        assert set(fake.attempts) == {0}  # the deadline ended the build inside chunk 0

    async def test_two_exhausted_chunks_abort_the_loop(self, clock):
        fake = _FakeHA(clock=clock, fail=_fail_all())
        await _call(fake)
        assert fake.attempts == {0: 3, 1: 3}
        assert len(fake.requests) == 6


# ---- partial window ---------------------------------------------------------------


class TestPartialWindow:
    async def test_six_of_seven_days_equals_the_mean_and_is_not_rescaled(self, clock):
        reference = await _reference(clock)
        profile = await _call(_FakeHA(clock=clock, fail=_fail_days({2})))
        assert profile == pytest.approx(reference)
        assert sum(profile) == pytest.approx(sum(reference))  # not 6/7 of it
        status = get_load_forecast_status()
        assert (status["status"], status["reason"]) == ("degraded", "partial")
        assert "6 of 7 days" in status["detail"]

    async def test_a_gap_on_a_fetched_day_does_not_count_as_zero(self, clock):
        reference = await _reference(clock)
        gapped = [p for p in PATTERN] + [
            (datetime(2026, 9, 17, 3, tzinfo=pytz.UTC), "unavailable"),
            (datetime(2026, 9, 17, 9, tzinfo=pytz.UTC), 2.0),
        ]
        profile = await _call(_FakeHA(gapped, clock=clock, fail=_fail_days({0})))
        assert profile == pytest.approx(reference)

    async def test_three_of_seven_days_is_a_transient_failure(self, clock):
        # Days 5 and 6 fail back to back, which ends the loop with days 0, 2, 4 fetched.
        fake = _FakeHA(clock=clock, fail=_fail_days({1, 3, 5, 6}))
        profile = await _call(fake)
        assert profile == [0.5] * 96
        status = get_load_forecast_status()
        assert (status["status"], status["reason"]) == ("degraded", "demo")
        assert "3 of 7 days" in status["detail"]

    async def test_four_of_seven_days_meets_the_floor(self, clock):
        profile = await _call(_FakeHA(clock=clock, fail=_fail_days({1, 3, 5})))
        assert sum(profile) == pytest.approx(36.0)
        assert get_load_forecast_status()["reason"] == "partial"

    async def test_floor_comes_before_the_supported_slot_rule(self, clock):
        """Fewer than 4 days is transient even when the fetched days look like bad data."""
        # Only 8 hours of valid data a day: 32 of 96 slots, below the 48-slot rule.
        sparse = _daily({0: 1.0, 8 * HOUR: "unavailable"})
        stored = await _call(_FakeHA(clock=clock))  # a good profile to fall back to
        ha_client.reset_load_profile_state()
        fake = _FakeHA(sparse, clock=clock, fail=_fail_days({1, 3, 5, 6}))
        assert await _call(fake) == pytest.approx(stored)
        assert get_load_forecast_status()["reason"] == "stale"

    async def test_supported_slot_rule_applies_after_the_floor(self, clock):
        """With enough days the 48-of-96 rule is a data problem: no stored profile."""
        await _call(_FakeHA(clock=clock))  # stores a good profile
        sparse = _daily({0: 1.0, 8 * HOUR: "unavailable"})
        profile = await _call(
            _FakeHA(sparse, clock=clock, fail=_fail_days({1, 3, 5})), force_refresh=True
        )
        assert profile == [0.5] * 96
        status = get_load_forecast_status()
        assert status["reason"] == "demo"
        assert "of 96" in status["detail"]
        assert ha_client._load_profile_failure is None


# ---- last good profile ------------------------------------------------------------


def _stored_file() -> dict:
    return json.loads(ha_client._LOAD_PROFILE_STORE_PATH.read_text())


class TestLastGoodProfile:
    async def test_round_trip(self, clock):
        profile = await _call(_FakeHA(clock=clock))
        stored = _stored_file()
        assert stored["version"] == 1
        assert stored["sensor"] == ENTITY
        assert stored["days_used"] == 7 and stored["days_total"] == 7
        assert stored["built_at"] == FIXED_NOW.isoformat()
        assert stored["profile"] == pytest.approx(profile)

    async def test_partial_profile_is_stored_with_days_used(self, clock):
        await _call(_FakeHA(clock=clock, fail=_fail_days({2})))
        assert _stored_file()["days_used"] == 6

    async def test_restart_during_an_outage_uses_the_file(self, clock):
        profile = await _call(_FakeHA(clock=clock))
        ha_client.reset_load_profile_state()  # a restart loses memory, not the file
        again = await _call(_FakeHA(clock=clock, fail=_fail_all()))
        assert again == pytest.approx(profile)
        assert get_load_forecast_status()["reason"] == "stale"

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda d: d.update(built_at=(FIXED_NOW - timedelta(days=7, seconds=1)).isoformat()),
            lambda d: d.update(sensor="sensor.other"),
            lambda d: d.update(built_at=(FIXED_NOW + timedelta(minutes=1)).isoformat()),
            lambda d: d.update(built_at="not a time"),
            lambda d: d.update(built_at=FIXED_NOW.replace(tzinfo=None).isoformat()),
            lambda d: d.update(version=99),
            lambda d: d.update(profile=[0.25] * 95),
            lambda d: d.update(profile=[-0.1] + [0.25] * 95),
            lambda d: d.update(profile=[0.0] * 96),
            lambda d: d.update(profile=[6.0] * 96),
            lambda d: d.update(profile=["x"] + [0.25] * 95),
        ],
        ids=[
            "stale", "other-sensor", "future", "unparsable", "naive", "version",
            "short", "negative", "zero-total", "over-500", "not-numbers",
        ],
    )
    async def test_invalid_stored_profile_is_ignored(self, clock, mutate):
        await _call(_FakeHA(clock=clock))
        data = _stored_file()
        mutate(data)
        ha_client._LOAD_PROFILE_STORE_PATH.write_text(json.dumps(data))
        ha_client.reset_load_profile_state()
        profile = await _call(_FakeHA(clock=clock, fail=_fail_all()))
        assert profile == [0.5] * 96
        assert get_load_forecast_status()["reason"] == "demo"

    async def test_corrupt_json_is_ignored(self, clock):
        await _call(_FakeHA(clock=clock))
        ha_client._LOAD_PROFILE_STORE_PATH.write_text("{not json")
        ha_client.reset_load_profile_state()
        profile = await _call(_FakeHA(clock=clock, fail=_fail_all()))
        assert profile == [0.5] * 96

    async def test_disk_write_failure_is_ignored(self, clock, caplog):
        with (
            patch("backend.core.ha_client.write_json_atomic", side_effect=OSError("disk full")),
            caplog.at_level(logging.WARNING, logger="darkstar.core.ha_client"),
        ):
            profile = await _call(_FakeHA(clock=clock))
        assert sum(profile) == pytest.approx(36.0)
        assert "OSError" in caplog.text
        # The in-memory copy still serves a later failure.
        again = await _call(_FakeHA(clock=clock, fail=_fail_all()), force_refresh=True)
        assert again == pytest.approx(profile)


# ---- fallback order ----------------------------------------------------------------


class TestFallbackOrder:
    async def test_all_chunks_fail_returns_the_stored_profile(self, clock):
        profile = await _call(_FakeHA(clock=clock))
        again = await _call(_FakeHA(clock=clock, fail=_fail_all()), force_refresh=True)
        assert again == pytest.approx(profile)

    async def test_empty_history_never_returns_the_stored_profile(self, clock):
        await _call(_FakeHA(clock=clock))
        profile = await _call(_FakeHA([], clock=clock), force_refresh=True)
        assert profile == [0.5] * 96
        assert "no history" in get_load_forecast_status()["detail"]

    async def test_implausible_data_never_returns_the_stored_profile(self, clock):
        await _call(_FakeHA(clock=clock))
        huge = _daily({0: 30.0})  # 720 kWh/day
        profile = await _call(_FakeHA(huge, clock=clock), force_refresh=True)
        assert profile == [0.5] * 96
        assert "plausibility" in get_load_forecast_status()["detail"]

    async def test_synthetic_estimate_does_not_outrank_a_valid_stored_profile(self, clock):
        profile = await _call(_FakeHA(clock=clock), SYNTHETIC_CONFIG)
        again = await _call(
            _FakeHA(clock=clock, fail=_fail_all()), SYNTHETIC_CONFIG, force_refresh=True
        )
        assert again == pytest.approx(profile)
        assert get_load_forecast_status()["reason"] == "stale"

    async def test_synthetic_estimate_applies_without_a_stored_profile(self, clock):
        profile = await _call(_FakeHA(clock=clock, fail=_fail_all()), SYNTHETIC_CONFIG)
        assert sum(profile) == pytest.approx(20.0)
        assert get_load_forecast_status()["reason"] == "estimated"


# ---- failure memo --------------------------------------------------------------------


class TestCooldown:
    async def _outage(self, clock, config=None):
        fake = _FakeHA(clock=clock, fail=_fail_all())
        return fake, await _call(fake, config)

    async def test_second_call_makes_no_request_and_returns_the_stored_profile(self, clock):
        good = await _call(_FakeHA(clock=clock))
        await _call(_FakeHA(clock=clock, fail=_fail_all()), force_refresh=True)
        second = _FakeHA(clock=clock)
        profile = await _call(second)
        assert second.requests == []
        assert profile == pytest.approx(good)
        assert get_load_forecast_status()["reason"] == "stale"

    async def test_second_call_without_a_stored_profile_returns_demo(self, clock):
        await self._outage(clock)
        second = _FakeHA(clock=clock)
        profile = await _call(second)
        assert second.requests == []
        assert profile == [0.5] * 96
        assert get_load_forecast_status()["reason"] == "demo"

    async def test_after_the_cooldown_one_new_build_runs(self, clock):
        await self._outage(clock)
        clock.advance(ha_client._LOAD_PROFILE_COOLDOWN_S)
        fake = _FakeHA(clock=clock)
        profile = await _call(fake)
        assert len(fake.requests) == 7
        assert sum(profile) == pytest.approx(36.0)

    async def test_success_clears_the_memo(self, clock):
        await self._outage(clock)
        recovered = _FakeHA(clock=clock)
        await _call(recovered, force_refresh=True)
        assert ha_client._load_profile_failure is None
        again = _FakeHA(clock=clock)
        await _call(again)
        assert len(again.requests) == 7

    async def test_a_different_sensor_ignores_the_memo(self, clock):
        await self._outage(clock)
        other = {"input_sensors": {"load_power": "sensor.other_load"}}
        fake = _FakeHA(clock=clock)
        await _call(fake, other)
        assert len(fake.requests) == 7

    async def test_force_refresh_bypasses_the_memo(self, clock):
        await self._outage(clock)
        fake = _FakeHA(clock=clock)
        await _call(fake, force_refresh=True)
        assert len(fake.requests) == 7

    async def test_empty_history_does_not_set_the_memo(self, clock):
        await _call(_FakeHA([], clock=clock))
        assert ha_client._load_profile_failure is None
        fake = _FakeHA([], clock=clock)
        await _call(fake)
        assert len(fake.requests) == 7

    async def test_implausible_data_does_not_set_the_memo(self, clock):
        await _call(_FakeHA(_daily({0: 30.0}), clock=clock))
        assert ha_client._load_profile_failure is None

    async def test_partial_window_is_not_an_outage(self, clock):
        await _call(_FakeHA(clock=clock, fail=_fail_days({2})))
        assert ha_client._load_profile_failure is None


class TestCoalescing:
    async def test_concurrent_calls_share_one_build(self, clock):
        fake = _FakeHA(clock=clock, yield_to_loop=True)
        results = await _call_concurrently(fake, 3)
        assert len(fake.requests) == 7
        assert results[0] == results[1] == results[2]
        assert ha_client._load_profile_in_flight == {}

    async def test_results_are_independent_copies(self, clock):
        fake = _FakeHA(clock=clock, yield_to_loop=True)
        first, second = await _call_concurrently(fake, 2)
        first[0] = 99.0
        assert second[0] != 99.0

    async def test_entry_removed_after_a_failed_build(self, clock):
        fake = _FakeHA(clock=clock, yield_to_loop=True, fail=_fail_all())
        await _call_concurrently(fake, 2)
        assert len(fake.requests) == 6
        assert ha_client._load_profile_in_flight == {}

    async def test_entry_removed_after_cancellation(self, clock):
        fake = _FakeHA(clock=clock, yield_to_loop=True)
        caller = asyncio.ensure_future(_call(fake))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        (build,) = ha_client._load_profile_in_flight.values()
        build.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert ha_client._load_profile_in_flight == {}

    async def test_cancelled_caller_does_not_cancel_the_shared_build(self, clock):
        fake = _FakeHA(clock=clock, yield_to_loop=True)
        # One patch context for the whole test: per-call contexts would be torn down
        # by the cancelled caller while the shared build is still running.
        with (
            patch("backend.core.ha_client.get_ha_http_client", return_value=fake.client),
            patch(
                "backend.core.secrets.load_home_assistant_config",
                return_value={"url": "http://homeassistant:8123", "token": "test_token"},
            ),
        ):
            first = asyncio.ensure_future(get_load_profile_from_ha(CONFIG))
            second = asyncio.ensure_future(get_load_profile_from_ha(CONFIG))
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            first.cancel()
            assert sum(await second) == pytest.approx(36.0)
        assert len(fake.requests) == 7
        assert ha_client._load_profile_in_flight == {}


class TestOutageCost:
    async def test_ten_calls_in_one_window_cost_at_most_one_deadline(self, clock):
        start = clock.now
        fake = _FakeHA(clock=clock, fail=_fail_all(httpx.ReadTimeout("")))
        for _ in range(10):
            await _call(fake)
        assert clock.now - start <= 60.0 + 1e-9
        assert set(fake.attempts) == {0}
        assert len(fake.requests) == 3

    async def test_planner_run_shape_makes_one_build(self, clock):
        fake = _FakeHA(clock=clock, fail=_fail_all())
        for _ in range(3):  # two planner calls and one API call
            await _call(fake)
        assert len(fake.requests) == 6


# ---- status and health ------------------------------------------------------------


class TestStatus:
    async def test_stored_profile_status_and_banner(self, clock):
        await _call(_FakeHA(clock=clock))
        await _call(_FakeHA(clock=clock, fail=_fail_all()), force_refresh=True)
        status = get_load_forecast_status()
        assert (status["status"], status["reason"]) == ("degraded", "stale")
        assert ENTITY in status["detail"] and "ago" in status["detail"]
        (issue,) = HealthChecker().check_load_forecast()
        text = f"{issue.message} {issue.guidance}".lower()
        assert "demo" not in text and "0.5 kwh flat" not in text
        assert "stored" in text and ENTITY in text
        assert issue.severity == "warning"

    async def test_partial_banner_is_informational(self, clock):
        await _call(_FakeHA(clock=clock, fail=_fail_days({2})))
        (issue,) = HealthChecker().check_load_forecast()
        assert issue.severity == "info"
        assert "6 of 7 days" in issue.guidance

    @pytest.mark.parametrize("reason", ["stale", "partial", "demo"])
    async def test_full_live_build_clears_ha_path_statuses(self, clock, reason):
        set_load_forecast_status("degraded", reason, "x")
        await _call(_FakeHA(clock=clock))
        assert get_load_forecast_status()["status"] == "ok"

    @pytest.mark.parametrize("reason", ["baseline", "no_ml"])
    async def test_full_live_build_leaves_ml_statuses(self, clock, reason):
        set_load_forecast_status("degraded", reason)
        await _call(_FakeHA(clock=clock))
        assert get_load_forecast_status()["reason"] == reason


async def test_debug_route_forces_a_refresh():
    from backend.api.routers import debug

    mock = AsyncMock(return_value=[0.25] * 96)
    with (
        patch.object(debug, "get_load_profile_from_ha", mock),
        patch.object(debug, "load_yaml", return_value=CONFIG),
    ):
        result = await debug.debug_load_profile()
    assert result["source"] == "ha"
    mock.assert_awaited_once_with(CONFIG, force_refresh=True)
