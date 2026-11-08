"""Tests for get_load_profile_from_ha (built from load_power history) and honest
degraded messaging (fix-beta-monitor-false-alarms, recorder-slot-aligned-energy).
"""

import logging
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from backend.core.ha_client import get_dummy_load_profile, get_load_profile_from_ha
from backend.health import clear_load_forecast_status, get_load_forecast_status

# Pinned "current time" for get_load_profile_from_ha. With a real clock, the
# local time of day of each synthetic sample shifts per run.
FIXED_NOW = datetime(2026, 9, 20, 12, 0, tzinfo=pytz.UTC)
ENTITY = "sensor.inverter_load_power"
CONFIG = {"timezone": "Europe/Stockholm", "input_sensors": {"load_power": ENTITY}}
STOCKHOLM = pytz.timezone("Europe/Stockholm")


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return FIXED_NOW if tz is None else FIXED_NOW.astimezone(tz)


@pytest.fixture(autouse=True)
def _frozen_clock():
    with patch("backend.core.ha_client.datetime", _FrozenDatetime):
        yield


@pytest.fixture(autouse=True)
def _reset_load_forecast_status():
    clear_load_forecast_status()
    yield
    clear_load_forecast_status()


def _state(value: float, ts: datetime, unit: str = "kW") -> dict:
    return {
        "entity_id": ENTITY,
        "state": str(value),
        "last_changed": ts.isoformat(),
        "attributes": {"unit_of_measurement": unit},
    }


class _FakeHA:
    """HA history endpoint over a power series of ``(timestamp, value)`` points.

    Like HA, a request returns the state held at the window start (stamped at the start)
    followed by the changes inside the window.
    """

    def __init__(self, points: list[tuple[datetime, float]], unit: str = "kW", error=None):
        self.points = sorted(points)
        self.unit = unit
        self.error = error
        self.requests: list[tuple[datetime, datetime]] = []
        self.client = MagicMock()
        self.client.get = AsyncMock(side_effect=self._get)

    async def _get(self, api_url, headers=None, params=None, timeout=None):
        if self.error:
            raise self.error
        start = datetime.fromisoformat(api_url.rsplit("/", 1)[1])
        end = datetime.fromisoformat(params["end_time"])
        self.requests.append((start, end))
        held = [p for p in self.points if p[0] <= start]
        states = [_state(held[-1][1], start, self.unit)] if held else []
        states += [_state(v, t, self.unit) for t, v in self.points if start < t < end]
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = [states] if states else []
        return response


async def _profile(fake: _FakeHA, config: dict | None = None) -> list[float]:
    with (
        patch("backend.core.ha_client.get_ha_http_client", return_value=fake.client),
        patch(
            "backend.core.secrets.load_home_assistant_config",
            return_value={"url": "http://homeassistant:8123", "token": "test_token"},
        ),
    ):
        return await get_load_profile_from_ha(config or CONFIG)


def _constant(kw: float, days: int = 8) -> list[tuple[datetime, float]]:
    return [(FIXED_NOW - timedelta(days=days), kw)]


class TestLoadProfileFromPower:
    @pytest.mark.asyncio
    async def test_constant_one_kw_gives_24_kwh_per_day(self):
        profile = await _profile(_FakeHA(_constant(1.0)))
        assert sum(profile) == pytest.approx(24.0)
        assert profile == [pytest.approx(0.25)] * 96
        assert get_load_forecast_status()["status"] != "degraded"

    @pytest.mark.asyncio
    async def test_watt_sensor_is_scaled(self):
        profile = await _profile(_FakeHA(_constant(1000.0), unit="W"))
        assert sum(profile) == pytest.approx(24.0)

    @pytest.mark.asyncio
    async def test_one_request_per_day(self):
        fake = _FakeHA(_constant(1.0))
        await _profile(fake)
        assert len(fake.requests) == 7
        assert all(end - start == timedelta(days=1) for start, end in fake.requests)
        assert fake.requests[0][0] == FIXED_NOW - timedelta(days=7)
        assert fake.requests[-1][1] == FIXED_NOW

    @pytest.mark.asyncio
    async def test_evening_peak_lands_in_its_local_slots(self):
        """A weekly 4 kW burst 18:00-19:00 local (CEST) maps to slots 72-75."""
        points: list[tuple[datetime, float]] = [(FIXED_NOW - timedelta(days=9), 0.0)]
        for day in range(-1, 8):
            base = datetime(2026, 9, 20, 16, 0, tzinfo=pytz.UTC) - timedelta(days=day)  # 18:00 CEST
            points += [(base, 4.0), (base + timedelta(hours=1), 0.0)]
        profile = await _profile(_FakeHA(points))
        for slot in range(96):
            expected = 1.0 if 72 <= slot <= 75 else 0.0
            assert profile[slot] == pytest.approx(expected, abs=1e-6)

    @pytest.mark.asyncio
    async def test_burst_across_local_midnight_wraps_into_slots_95_and_0(self):
        # 4 kW from 23:50 to 00:05 local on 2026-09-17 (CEST = UTC+2)
        start = datetime(2026, 9, 17, 21, 50, tzinfo=pytz.UTC)
        points = [
            (FIXED_NOW - timedelta(days=9), 0.0),
            (start, 4.0),
            (start + timedelta(minutes=15), 0.0),
        ]
        profile = await _profile(_FakeHA(points))
        assert sum(profile) == pytest.approx(1.0 / 7)
        assert profile[95] == pytest.approx(4.0 * 10 / 60 / 7)
        assert profile[0] == pytest.approx(4.0 * 5 / 60 / 7)

    @pytest.mark.asyncio
    async def test_dst_fall_back_repeats_the_hour_in_wall_clock_slots(self):
        """On 2026-10-25 (25 h day) 02:00-03:00 occurs twice, so its slots are sampled 8
        times in the window where every other slot is sampled 7 times. Each slot is the
        mean over its covered time, so the repeated hour is not inflated (a constant
        1 kW load stays 0.25 kWh in every slot); no energy is lost.
        """
        now = datetime(2026, 10, 27, 12, 0, tzinfo=pytz.UTC)

        class _DstNow(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                return now if tz is None else now.astimezone(tz)

        fake = _FakeHA([(now - timedelta(days=9), 1.0)])
        with patch("backend.core.ha_client.datetime", _DstNow):
            profile = await _profile(fake)

        assert sum(profile) == pytest.approx(24.0)
        assert profile[9] == pytest.approx(0.25)
        assert profile[60] == pytest.approx(0.25)


class TestUnusableHistory:
    @pytest.mark.asyncio
    async def test_over_500_kwh_per_day_names_the_sensor(self):
        profile = await _profile(_FakeHA(_constant(25.0)))  # 600 kWh/day
        assert profile == [0.5] * 96
        status = get_load_forecast_status()
        assert status["status"] == "degraded"
        assert ENTITY in status["detail"]
        assert "500 kWh/day" in status["detail"]
        assert "discarded" in status["detail"]

    @pytest.mark.asyncio
    async def test_empty_history_names_the_sensor(self):
        profile = await _profile(_FakeHA([]))
        assert profile == [0.5] * 96
        status = get_load_forecast_status()
        assert status["status"] == "degraded"
        assert ENTITY in status["detail"]
        assert "no history" in status["detail"]

    @pytest.mark.asyncio
    async def test_all_zero_history_is_unusable(self):
        profile = await _profile(_FakeHA(_constant(0.0)))
        assert profile == [0.5] * 96
        assert ENTITY in get_load_forecast_status()["detail"]

    @pytest.mark.asyncio
    async def test_failed_request_falls_back_and_names_the_sensor(self):
        profile = await _profile(_FakeHA([], error=TimeoutError("timed out")))
        assert profile == [0.5] * 96
        status = get_load_forecast_status()
        assert status["status"] == "degraded"
        assert ENTITY in status["detail"]

    @pytest.mark.asyncio
    async def test_synthetic_estimate_replaces_demo_when_history_is_empty(self):
        config = {
            "input_sensors": {"load_power": ENTITY, "synthetic_daily_load_kwh": 20},
        }
        profile = await _profile(_FakeHA([]), config)
        assert sum(profile) == pytest.approx(20.0)
        status = get_load_forecast_status()
        assert (status["status"], status["reason"]) == ("synthetic", "estimated")

    @pytest.mark.asyncio
    async def test_synthetic_estimate_replaces_demo_when_data_is_discarded(self):
        config = {
            "input_sensors": {"load_power": ENTITY, "synthetic_daily_load_kwh": 20},
        }
        profile = await _profile(_FakeHA(_constant(25.0)), config)
        assert sum(profile) == pytest.approx(20.0)

    @pytest.mark.asyncio
    async def test_history_takes_precedence_over_synthetic_estimate(self):
        config = {
            "input_sensors": {"load_power": ENTITY, "synthetic_daily_load_kwh": 20},
        }
        profile = await _profile(_FakeHA(_constant(1.0)), config)
        assert sum(profile) == pytest.approx(24.0)
        assert get_load_forecast_status()["status"] != "degraded"


class TestDegradedMessaging:
    def test_not_configured_message_instructs_configuration(self, caplog):
        with caplog.at_level(logging.WARNING):
            get_dummy_load_profile({"input_sensors": {}})
        status = get_load_forecast_status()
        assert status["status"] == "degraded"
        assert status["reason"] == "demo"
        assert status["detail"] == ""
        assert "load_power" in caplog.text
        assert "total_load_consumption" not in caplog.text

    def test_configured_but_discarded_message_names_sensor(self):
        get_dummy_load_profile(
            {"input_sensors": {}},
            discard_reason=(
                f"'{ENTITY}' data discarded: 900.0 kWh/day exceeds the 500 kWh/day plausibility bound"
            ),
        )
        status = get_load_forecast_status()
        assert status["status"] == "degraded"
        assert status["reason"] == "demo"
        assert ENTITY in status["detail"]
        assert "discarded" in status["detail"]

    @pytest.mark.asyncio
    async def test_missing_ha_configuration_uses_dummy(self):
        with patch("backend.core.secrets.load_home_assistant_config", return_value={}):
            profile = await get_load_profile_from_ha(CONFIG)
        assert profile == [0.5] * 96

    @pytest.mark.asyncio
    async def test_unconfigured_load_power_uses_dummy_without_request(self):
        fake = _FakeHA(_constant(1.0))
        profile = await _profile(fake, {"input_sensors": {}})
        assert profile == [0.5] * 96
        assert fake.requests == []

    def test_degraded_guidance_names_load_power(self):
        from backend.health import HealthChecker

        get_dummy_load_profile({"input_sensors": {}})
        issues = HealthChecker().check_load_forecast()
        assert issues
        assert "load_power" in issues[0].guidance
        assert "total_load_consumption" not in issues[0].guidance


def _daily(values: dict[int, object], days: range = range(-1, 9)) -> list[tuple[datetime, object]]:
    """Repeat a UTC time-of-day pattern (``{second_of_day: value}``) on every day.

    ``value`` may be the string ``"unavailable"`` to open a sensor gap.
    """
    midnight = datetime(2026, 9, 20, tzinfo=pytz.UTC)
    return [
        (midnight - timedelta(days=day) + timedelta(seconds=sec), value)
        for day in days
        for sec, value in values.items()
    ]


HOUR = 3600


class TestPerSlotCoverageAveraging:
    """fix-load-profile-coverage-averaging: a slot is averaged only over valid time."""

    @pytest.mark.asyncio
    async def test_six_hour_outage_on_one_day_does_not_lower_the_profile(self):
        # 2 kW 00-12 UTC, 1 kW 12-24 UTC every day: a non-flat reference profile.
        pattern = _daily({0: 2.0, 12 * HOUR: 1.0})
        reference = await _profile(_FakeHA(pattern))

        # Same pattern, but on 2026-09-16 the sensor is unavailable 03:00-09:00 UTC.
        outage_start = datetime(2026, 9, 16, 3, 0, tzinfo=pytz.UTC)
        gap = [(outage_start, "unavailable"), (outage_start + timedelta(hours=6), 2.0)]
        profile = await _profile(_FakeHA(pattern + gap))

        assert profile == [pytest.approx(v) for v in reference]
        # 05:00-11:00 local (slots 20-43) keep 2 kW (0.5 kWh), not 6/7 of it.
        assert profile[20] == pytest.approx(0.5)
        assert profile[43] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_partial_slot_outage_is_exact(self):
        # 1 kW all week. On 2026-09-16 the sensor is unavailable 03:00-03:10 UTC and
        # reads 3 kW for the last 5 minutes of that slot (local slot 20, 05:00 CEST).
        t = datetime(2026, 9, 16, 3, 0, tzinfo=pytz.UTC)
        points = [
            *_constant(1.0),
            (t, "unavailable"),
            (t + timedelta(minutes=10), 3.0),
            (t + timedelta(minutes=15), 1.0),
        ]
        profile = await _profile(_FakeHA(points))

        energy = 6 * 0.25 + 3.0 * 5 / 60  # kWh actually measured in the slot
        covered = 6 * 900 + 300  # seconds of valid data in the slot
        assert profile[20] == pytest.approx(energy / covered * 900)
        assert profile[19] == pytest.approx(0.25)
        assert profile[21] == pytest.approx(0.25)

    @pytest.mark.asyncio
    async def test_fully_covered_days_are_the_plain_mean(self):
        # Each of the 7 request windows (12:00 UTC to 12:00 UTC) holds 1..7 kW, so every
        # slot is sampled once per window and its mean is 4 kW, i.e. 1 kWh per slot.
        window_start = FIXED_NOW - timedelta(days=7)
        points = [(window_start - timedelta(days=1), 1.0)] + [
            (window_start + timedelta(days=i), float(i + 1)) for i in range(7)
        ]
        profile = await _profile(_FakeHA(points))
        assert profile == [pytest.approx(1.0)] * 96

    @pytest.mark.asyncio
    async def test_slot_never_covered_is_interpolated_from_neighbours(self):
        # Every day: 2 kW, sensor unavailable 22:00-23:00 UTC (local slots 0-3), then
        # 1 kW from 23:00 UTC (local slot 4) until the next 00:00 UTC.
        pattern = _daily({0: 2.0, 22 * HOUR: "unavailable", 23 * HOUR: 1.0})
        profile = await _profile(_FakeHA(pattern))

        assert profile[95] == pytest.approx(0.5)
        assert profile[4] == pytest.approx(0.25)
        for slot in range(4):
            expected = 0.5 + (0.25 - 0.5) * (slot + 1) / 5
            assert profile[slot] == pytest.approx(expected)
        assert get_load_forecast_status()["status"] != "degraded"

    @pytest.mark.asyncio
    async def test_mostly_uncovered_profile_is_insufficient(self):
        # Valid data only 18:00-24:00 UTC every day (24 of 96 slots): below the floor.
        pattern = _daily({0: "unavailable", 18 * HOUR: 1.0})
        profile = await _profile(_FakeHA(pattern))
        assert profile == [0.5] * 96
        status = get_load_forecast_status()
        assert status["status"] == "degraded"
        assert ENTITY in status["detail"]
        assert "24 of 96" in status["detail"]

    @pytest.mark.asyncio
    async def test_total_outage_is_empty_history_not_zero_load(self):
        pattern = _daily({0: "unavailable"})
        profile = await _profile(_FakeHA(pattern))
        assert profile == [0.5] * 96
        assert get_load_forecast_status()["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_plausibility_bound_still_applies_after_coverage_averaging(self):
        pattern = _daily({0: 25.0, 3 * HOUR: "unavailable", 4 * HOUR: 25.0})
        profile = await _profile(_FakeHA(pattern))
        assert profile == [0.5] * 96
        assert "500 kWh/day" in get_load_forecast_status()["detail"]

    def test_integration_reports_covered_seconds(self):
        from backend.core.ha_client import integrate_power_points_covered, parse_power_states

        start = datetime(2026, 9, 20, 3, 0, tzinfo=pytz.UTC)
        end = start + timedelta(minutes=15)
        states = [
            _state(2.0, start),
            {**_state(0.0, start + timedelta(minutes=5)), "state": "unavailable"},
            _state(2.0, start + timedelta(minutes=10)),
        ]
        result = integrate_power_points_covered(parse_power_states(states, ENTITY), start, end)
        assert result is not None
        positive, negative, covered = result
        assert covered == pytest.approx(600.0)
        assert positive == pytest.approx(2.0 * 10 / 60)
        assert negative == 0.0
        assert integrate_power_points_covered([], start, end) is None
