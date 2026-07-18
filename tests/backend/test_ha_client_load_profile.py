"""Tests for get_load_profile_from_ha's per-delta sanity guard and honest
degraded messaging (fix-beta-monitor-false-alarms).
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from backend.core.ha_client import get_dummy_load_profile, get_load_profile_from_ha
from backend.health import clear_load_forecast_status, get_load_forecast_status


def _fresh_start() -> datetime:
    """A timestamp safely inside the function's trailing-7-day query window.

    get_load_profile_from_ha computes its own `now` internally, so synthetic
    history must be generated relative to real wall-clock time, with enough
    buffer that clock drift between generation and the call never pushes a
    data point before the query's start_time.
    """
    return datetime.now(pytz.UTC) - timedelta(days=7) + timedelta(minutes=20)


def _state(value: str, ts: datetime, unit: str = "kWh") -> dict:
    return {
        "state": value,
        "last_changed": ts.isoformat(),
        "attributes": {"unit_of_measurement": unit},
    }


def _clean_lifetime_states(days: int = 6, daily_kwh: float = 10.0) -> list[dict]:
    """Plausible cumulative-meter history: steady small per-slot increments."""
    start = _fresh_start()
    per_step = daily_kwh / 96
    lifetime = 19600.0
    states = []
    for day in range(days):
        for step in range(96):
            t = start + timedelta(days=day, minutes=15 * step)
            lifetime += per_step
            states.append(_state(f"{lifetime:.4f}", t))
    return states


def _lifetime_states_with_nightly_reset(days: int = 6, daily_kwh: float = 10.0) -> list[dict]:
    """Cumulative-meter history with a Fronius-style nightly 0->lifetime jump.

    Each day, one slot reads 0 (meter reset) and the next slot jumps back up
    to the true cumulative value, matching the beta-tester evidence
    (~19,600 kWh jumps, once per day).
    """
    start = _fresh_start()
    per_step = daily_kwh / 96
    lifetime = 19600.0
    states = []
    for day in range(days):
        for step in range(96):
            t = start + timedelta(days=day, minutes=15 * step)
            if step == 12:
                states.append(_state("0.0", t))
                continue
            lifetime += per_step
            states.append(_state(f"{lifetime:.4f}", t))
    return states


async def _run_get_load_profile(states: list[dict], config: dict | None = None) -> list[float]:
    mock_response = MagicMock()
    mock_response.json.return_value = [states]
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    cfg = config or {
        "timezone": "Europe/Stockholm",
        "input_sensors": {"total_load_consumption": "sensor.fronius_lifetime"},
    }

    with (
        patch("backend.core.ha_client.get_ha_http_client", return_value=mock_client),
        patch(
            "backend.core.secrets.load_home_assistant_config",
            return_value={
                "url": "http://homeassistant:8123",
                "token": "test_token",
                "consumption_entity_id": "sensor.fronius_lifetime",
            },
        ),
    ):
        return await get_load_profile_from_ha(cfg)


@pytest.fixture(autouse=True)
def _reset_load_forecast_status():
    clear_load_forecast_status()
    yield
    clear_load_forecast_status()


class TestDeltaGuard:
    @pytest.mark.asyncio
    async def test_nightly_reset_produces_plausible_profile_not_demo(self):
        states = _lifetime_states_with_nightly_reset(daily_kwh=10.0)
        profile = await _run_get_load_profile(states)

        # Demo fallback is a flat 0.5 kWh * 96 slots; a real profile built
        # from ~10 kWh/day of genuine deltas looks nothing like that.
        assert profile != [0.5] * 96
        assert sum(profile) < 500
        status = get_load_forecast_status()
        assert status["status"] != "degraded"

    @pytest.mark.asyncio
    async def test_clean_history_unaffected_by_guard(self):
        states = _clean_lifetime_states(daily_kwh=10.0)
        profile = await _run_get_load_profile(states)

        assert profile != [0.5] * 96
        assert 3.0 < sum(profile) < 20.0
        status = get_load_forecast_status()
        assert status["status"] != "degraded"

    @pytest.mark.asyncio
    async def test_skip_warning_logged_once(self, caplog):
        import logging

        states = _lifetime_states_with_nightly_reset(days=6, daily_kwh=10.0)
        with caplog.at_level(logging.WARNING, logger="darkstar.core.ha_client"):
            await _run_get_load_profile(states)

        skip_warnings = [
            r for r in caplog.records if "implausible cumulative-meter delta" in r.message
        ]
        assert len(skip_warnings) == 1
        assert "6 implausible" in skip_warnings[0].message

    @pytest.mark.asyncio
    async def test_custom_max_meter_delta_kwh_is_honored(self):
        """A delta below the configured max is NOT skipped even if unusually large."""
        baseline_states = _clean_lifetime_states(daily_kwh=10.0)
        baseline_profile = await _run_get_load_profile(baseline_states)

        states = _clean_lifetime_states(daily_kwh=10.0)
        # Inject one 30 kWh jump, plausible under a raised 100 kWh config max.
        prev_val = float(states[49]["state"])
        states[50] = _state(
            f"{prev_val + 30.0:.4f}", datetime.fromisoformat(states[50]["last_changed"])
        )
        config = {
            "timezone": "Europe/Stockholm",
            "input_sensors": {"total_load_consumption": "sensor.fronius_lifetime"},
            "recorder": {"max_meter_delta_kwh": 100.0},
        }
        profile = await _run_get_load_profile(states, config=config)
        assert profile != [0.5] * 96
        # the 30 kWh jump should be counted, not skipped: total rises by ~30/7 kWh/day
        assert sum(profile) - sum(baseline_profile) > 3.0


class TestDegradedMessaging:
    def test_not_configured_message_instructs_configuration(self):
        clear_load_forecast_status()
        get_dummy_load_profile({"input_sensors": {}})
        status = get_load_forecast_status()
        assert status["status"] == "degraded"
        assert status["reason"] == "demo"
        assert status["detail"] == ""

    def test_configured_but_discarded_message_names_sensor(self):
        clear_load_forecast_status()
        get_dummy_load_profile(
            {"input_sensors": {}},
            discard_reason=(
                "'sensor.fronius_lifetime' data discarded: 19609.2 kWh/day exceeds the "
                "500 kWh/day plausibility bound"
            ),
        )
        status = get_load_forecast_status()
        assert status["status"] == "degraded"
        assert status["reason"] == "demo"
        assert "sensor.fronius_lifetime" in status["detail"]
        assert "discarded" in status["detail"]

    @pytest.mark.asyncio
    async def test_total_daily_over_500_passes_discard_reason_to_dummy(self):
        """A whole-profile bound violation (unskippable pattern of sub-threshold
        deltas summing over 500 kWh/day) still names the sensor, not 'not configured'."""
        # Deltas each just under the 50 kWh guard, but frequent enough that the
        # 500 kWh/day backstop trips.
        start = _fresh_start()
        per_step = 40.0
        lifetime = 0.0
        states = []
        for step in range(96):
            t = start + timedelta(minutes=15 * step)
            lifetime += per_step
            states.append(_state(f"{lifetime:.4f}", t))

        clear_load_forecast_status()
        profile = await _run_get_load_profile(states)
        assert profile == [0.5] * 96  # demo fallback
        status = get_load_forecast_status()
        assert status["status"] == "degraded"
        assert status["reason"] == "demo"
        assert "sensor.fronius_lifetime" in status["detail"]
        assert "500 kWh/day" in status["detail"]
