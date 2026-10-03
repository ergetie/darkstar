"""Unit tests for the shared power-history integrator and the batched history fetch."""

import logging
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from backend.core.ha_client import (
    get_energy_from_power_history,
    get_power_history_batch,
    integrate_power_points,
    parse_power_states,
)

START = datetime(2024, 1, 1, 10, 0, tzinfo=pytz.UTC)
END = START + timedelta(minutes=15)


def _state(value: str, minutes: float, unit: str | None = "kW", entity: str | None = None) -> dict:
    state: dict = {
        "state": value,
        "last_changed": (START + timedelta(minutes=minutes)).isoformat(),
    }
    if unit is not None:
        state["attributes"] = {"unit_of_measurement": unit}
    if entity is not None:
        state["entity_id"] = entity
    return state


def _integrate(states: list[dict]) -> tuple[float, float] | None:
    return integrate_power_points(parse_power_states(states), START, END)


class TestIntegratePowerPoints:
    def test_positive_and_negative_split_by_sample_interval(self):
        """+2 kW for 5 min then -4 kW for 10 min."""
        result = _integrate([_state("2.0", 0), _state("-4.0", 5)])
        assert result is not None
        positive, negative = result
        assert positive == pytest.approx(2.0 * 5 / 60)
        assert negative == pytest.approx(4.0 * 10 / 60)

    def test_sign_flip_inside_window_is_not_netted(self):
        result = _integrate([_state("3.0", 0), _state("-3.0", 7.5)])
        assert result == (pytest.approx(3.0 * 7.5 / 60), pytest.approx(3.0 * 7.5 / 60))

    def test_pre_window_state_is_held_from_window_start(self):
        result = _integrate([_state("6.0", -30), _state("0.0", 5)])
        assert result == (pytest.approx(0.5), 0.0)

    def test_state_after_window_is_ignored(self):
        result = _integrate([_state("1.0", 0), _state("9.0", 20)])
        assert result == (pytest.approx(0.25), 0.0)

    def test_unit_is_propagated_to_states_without_one(self):
        """HA reports the unit on the first state only: W applies to the rest."""
        states = [_state("1000", 0, unit="W"), _state("2000", 7.5, unit=None)]
        positive, negative = _integrate(states) or (None, None)
        assert positive == pytest.approx(1.0 * 7.5 / 60 + 2.0 * 7.5 / 60)
        assert negative == 0.0

    def test_megawatt_is_scaled(self):
        assert _integrate([_state("0.001", 0, unit="MW")]) == (pytest.approx(0.25), 0.0)

    def test_no_valid_points_returns_none(self):
        assert _integrate([_state("unavailable", 0), _state("unknown", 5), _state("x", 6)]) is None
        assert _integrate([]) is None

    def test_points_only_after_window_integrate_to_zero(self):
        assert _integrate([_state("5.0", 30)]) == (0.0, 0.0)

    def test_many_windows_over_one_series_use_each_pre_window_state(self):
        points = parse_power_states([_state("4.0", -10), _state("8.0", 15)])
        first = integrate_power_points(points, START, END)
        second = integrate_power_points(points, END, END + timedelta(minutes=15))
        assert first == (pytest.approx(1.0), 0.0)
        assert second == (pytest.approx(2.0), 0.0)


def _mock_client(payload=None, error: Exception | None = None) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    client = MagicMock()
    client.get = AsyncMock(return_value=response, side_effect=error)
    return client


def _patched(client: MagicMock):
    return (
        patch(
            "backend.core.ha_client.secrets.load_home_assistant_config",
            return_value={"url": "http://ha.local", "token": "tok"},
        ),
        patch("backend.core.ha_client.get_ha_http_client", return_value=client),
    )


class TestGetPowerHistoryBatch:
    @pytest.mark.asyncio
    async def test_one_request_returns_one_series_per_entity(self):
        client = _mock_client(
            [
                [
                    _state("1000", 0, unit="W", entity="sensor.a"),
                    _state("2000", 5, None, "sensor.a"),
                ],
                [_state("-3.0", 0, unit="kW", entity="sensor.b")],
            ]
        )
        secrets_patch, client_patch = _patched(client)
        with secrets_patch, client_patch:
            history = await get_power_history_batch(["sensor.a", "sensor.b"], START, END)

        assert client.get.await_count == 1
        params = client.get.await_args.kwargs["params"]
        assert params["filter_entity_id"] == "sensor.a,sensor.b"
        assert client.get.await_args.kwargs["timeout"] == 12.0
        assert history is not None
        # Unit propagation works per entity: sensor.a is W on every state
        a = integrate_power_points(parse_power_states(history["sensor.a"]), START, END)
        b = integrate_power_points(parse_power_states(history["sensor.b"]), START, END)
        assert a == (pytest.approx(1.0 * 5 / 60 + 2.0 * 10 / 60), 0.0)
        assert b == (0.0, pytest.approx(0.75))

    @pytest.mark.asyncio
    async def test_duplicate_and_empty_entities_are_collapsed(self):
        client = _mock_client([])
        secrets_patch, client_patch = _patched(client)
        with secrets_patch, client_patch:
            history = await get_power_history_batch(["sensor.a", "sensor.a", ""], START, END)
        assert client.get.await_args.kwargs["params"]["filter_entity_id"] == "sensor.a"
        assert history == {"sensor.a": []}

    @pytest.mark.asyncio
    async def test_entity_missing_from_response_gets_empty_series(self):
        client = _mock_client([[_state("1.0", 0, entity="sensor.a")], []])
        secrets_patch, client_patch = _patched(client)
        with secrets_patch, client_patch:
            history = await get_power_history_batch(["sensor.a", "sensor.b"], START, END)
        assert history is not None
        assert history["sensor.b"] == []
        assert len(history["sensor.a"]) == 1

    @pytest.mark.asyncio
    async def test_failed_request_returns_none_and_warns_once(self, caplog):
        client = _mock_client(error=TimeoutError("timed out"))
        secrets_patch, client_patch = _patched(client)
        with secrets_patch, client_patch, caplog.at_level(logging.WARNING):
            history = await get_power_history_batch(["sensor.a", "sensor.b"], START, END)
        assert history is None
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1

    @pytest.mark.asyncio
    async def test_missing_ha_config_makes_no_request(self):
        client = _mock_client([])
        with (
            patch("backend.core.ha_client.secrets.load_home_assistant_config", return_value={}),
            patch("backend.core.ha_client.get_ha_http_client", return_value=client),
        ):
            assert await get_power_history_batch(["sensor.a"], START, END) is None
        client.get.assert_not_awaited()


class TestGetEnergyFromPowerHistoryWrapper:
    @pytest.mark.asyncio
    async def test_returns_signed_sum_as_before(self):
        client = _mock_client([[_state("2.0", 0), _state("-4.0", 5)]])
        secrets_patch, client_patch = _patched(client)
        with secrets_patch, client_patch:
            result = await get_energy_from_power_history("sensor.ev", START, END)
        assert result == pytest.approx(2.0 * 5 / 60 - 4.0 * 10 / 60)

    @pytest.mark.asyncio
    async def test_empty_history_returns_none(self):
        client = _mock_client([])
        secrets_patch, client_patch = _patched(client)
        with secrets_patch, client_patch:
            assert await get_energy_from_power_history("sensor.ev", START, END) is None

    @pytest.mark.asyncio
    async def test_failed_request_returns_none(self):
        client = _mock_client(error=RuntimeError("boom"))
        secrets_patch, client_patch = _patched(client)
        with secrets_patch, client_patch:
            assert await get_energy_from_power_history("sensor.ev", START, END) is None
