"""Unit tests for the shared power-history integrator and the batched history fetch."""

import logging
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from backend.core import ha_client
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


class TestUnavailableEndsTheHold:
    """A state that is not a reading ends the hold; only valid intervals add energy."""

    @pytest.mark.parametrize("gap_state", ["unavailable", "unknown", "", "n/a"])
    def test_valid_then_unavailable_mid_slot(self, gap_state):
        """08:00 shape: 2 kW valid for 26 s, then no reading to the end of the slot."""
        result = _integrate([_state("2.0", 0), _state(gap_state, 26 / 60)])
        assert result == (pytest.approx(2.0 * 26 / 3600), 0.0)
        assert result[0] == pytest.approx(0.0144, abs=1e-4)

    @pytest.mark.parametrize("gap_state", ["unavailable", "unknown"])
    def test_unavailable_then_valid_mid_slot(self, gap_state):
        """12:15 shape: unavailable at the slot start, back after 518 s."""
        result = _integrate([_state(gap_state, 0), _state("2.0", 518 / 60)])
        assert result == (pytest.approx(2.0 * (900 - 518) / 3600), 0.0)

    def test_multiple_flaps_add_only_valid_intervals(self):
        states = [
            _state("1.0", 0),
            _state("unavailable", 2),
            _state("3.0", 5),
            _state("unknown", 8),
            _state("unavailable", 9),
            _state("2.0", 12),
        ]
        # 1 kW x 2 min + 3 kW x 3 min + 2 kW x 3 min
        assert _integrate(states) == (pytest.approx((1 * 2 + 3 * 3 + 2 * 3) / 60), 0.0)

    def test_negative_energy_is_not_held_across_a_gap_either(self):
        result = _integrate([_state("-4.0", 0), _state("unavailable", 3)])
        assert result == (0.0, pytest.approx(4.0 * 3 / 60))

    def test_window_inside_an_unavailable_period_has_no_value(self):
        """A pre-window valid value is not held through a later unavailable state."""
        points = parse_power_states([_state("2.0", -30), _state("unavailable", -10)])
        assert integrate_power_points(points, START, END) is None

    def test_gap_state_keeps_learning_the_unit(self):
        points = parse_power_states([_state("unavailable", 0, unit="W"), _state("1500", 5, None)])
        assert [value for _ts, value in points] == [None, 1.5]

    def test_gap_markers_are_time_sorted_with_valid_points(self):
        points = parse_power_states([_state("2.0", 10), _state("unavailable", 5), _state("1.0", 0)])
        assert [value for _ts, value in points] == [1.0, None, 2.0]


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

    def test_unchanged_sensor_holds_start_of_window_state_for_the_whole_window(self):
        """HA returns only the start-of-window state when nothing changed: not a gap."""
        assert _integrate([_state("2.0", -600)]) == (pytest.approx(0.5), 0.0)
        assert _integrate([_state("0.0", -600)]) == (0.0, 0.0)
        assert _integrate([_state("-4.0", -600)]) == (0.0, pytest.approx(1.0))

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

    def test_points_only_after_window_have_no_value(self):
        """No valid interval overlaps the window, so there is nothing to report."""
        assert _integrate([_state("5.0", 30)]) is None

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


class TestParsePowerStatesUnitLearning:
    def test_unit_learned_from_leading_non_numeric_state(self):
        """A chunk starting `unavailable` (unit on it) keeps W for the unitless states after."""
        for leading in ("unavailable", "unknown"):
            states = [
                _state(leading, 0, unit="W"),
                _state("1000", 5, None),
                _state("2000", 10, None),
            ]
            result = _integrate(states)
            assert result is not None
            assert result[0] == pytest.approx(1.0 * 5 / 60 + 2.0 * 5 / 60)

    def test_normal_series_unchanged(self):
        points = parse_power_states([_state("1000", 0, unit="W"), _state("2000", 5, None)])
        assert [value for _ts, value in points] == [1.0, 2.0]

    def test_unit_unknown_assumes_kw_and_warns_once_per_entity(self, caplog):
        ha_client._unitless_warned.clear()
        states = [_state("2.0", 0, unit=None), _state("3.0", 5, unit=None)]
        with caplog.at_level(logging.WARNING, logger="darkstar.core.ha_client"):
            first = parse_power_states(states, "sensor.nounit")
            parse_power_states(states, "sensor.nounit")
            parse_power_states(states, "sensor.other")
        assert [value for _ts, value in first] == [2.0, 3.0]
        messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert len(messages) == 2
        assert "sensor.nounit" in messages[0]
        assert "sensor.other" in messages[1]


class TestGetPowerHistoryBatch:
    @pytest.mark.asyncio
    async def test_request_params_are_explicit_strings(self):
        client = _mock_client([[_state("1.0", 0, entity="sensor.a")]])
        secrets_patch, client_patch = _patched(client)
        with secrets_patch, client_patch:
            await get_power_history_batch(["sensor.a"], START, END)
        params = client.get.await_args.kwargs["params"]
        assert params["significant_changes_only"] == "0"
        assert params["minimal_response"] == "true"
        assert False not in params.values()

    @pytest.mark.asyncio
    async def test_unitless_series_gets_current_unit_without_mutating_source(self):
        series = [_state("1000", 0, None, "sensor.a"), _state("2000", 5, None, "sensor.a")]
        client = _mock_client([series])
        secrets_patch, client_patch = _patched(client)
        state_mock = AsyncMock(return_value={"attributes": {"unit_of_measurement": "W"}})
        with (
            secrets_patch,
            client_patch,
            patch.object(ha_client, "get_ha_entity_state", state_mock),
        ):
            history = await get_power_history_batch(["sensor.a"], START, END)
        assert history is not None
        state_mock.assert_awaited_once_with("sensor.a")
        assert history["sensor.a"][0]["attributes"]["unit_of_measurement"] == "W"
        assert "attributes" not in series[0]
        assert integrate_power_points(parse_power_states(history["sensor.a"]), START, END) == (
            pytest.approx(1.0 * 5 / 60 + 2.0 * 10 / 60),
            0.0,
        )

    @pytest.mark.asyncio
    async def test_no_extra_request_when_series_has_unit(self):
        client = _mock_client([[_state("1000", 0, "W", "sensor.a")]])
        secrets_patch, client_patch = _patched(client)
        state_mock = AsyncMock()
        with (
            secrets_patch,
            client_patch,
            patch.object(ha_client, "get_ha_entity_state", state_mock),
        ):
            await get_power_history_batch(["sensor.a"], START, END)
        state_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failed_unit_lookup_leaves_series_unchanged(self):
        client = _mock_client(
            [[_state("1000", 0, None, "sensor.a")], [_state("1", 0, None, "sensor.b")]]
        )
        secrets_patch, client_patch = _patched(client)

        async def lookup(entity):
            if entity == "sensor.a":
                raise RuntimeError("boom")
            return {"attributes": {"unit_of_measurement": "W"}}

        with (
            secrets_patch,
            client_patch,
            patch.object(ha_client, "get_ha_entity_state", AsyncMock(side_effect=lookup)),
        ):
            history = await get_power_history_batch(["sensor.a", "sensor.b"], START, END)
        assert history is not None
        assert "attributes" not in history["sensor.a"][0]
        assert history["sensor.b"][0]["attributes"]["unit_of_measurement"] == "W"

    @pytest.mark.asyncio
    async def test_unavailable_lookup_result_leaves_series_unchanged(self):
        client = _mock_client([[_state("1000", 0, None, "sensor.a")]])
        secrets_patch, client_patch = _patched(client)
        with (
            secrets_patch,
            client_patch,
            patch.object(ha_client, "get_ha_entity_state", AsyncMock(return_value=None)),
        ):
            history = await get_power_history_batch(["sensor.a"], START, END)
        assert history is not None
        assert "attributes" not in history["sensor.a"][0]

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


class TestLoadProfileAfterOutage:
    @pytest.mark.asyncio
    async def test_day_chunk_starting_unavailable_stays_in_watts(self, monkeypatch):
        """Every day chunk opens `unavailable` (unit only there): W must not become kW."""
        # Fixed normal (non-DST) date: the 7-day window 2026-09-29..10-06 has no clock change.
        fixed_now = datetime(2026, 10, 6, 12, 0, tzinfo=pytz.UTC)

        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return (
                    fixed_now.astimezone(tz) if tz is not None else fixed_now.replace(tzinfo=None)
                )

        monkeypatch.setattr(ha_client, "datetime", FrozenDateTime)

        async def fake_history(entity_ids, start, end, **_kwargs):
            return {
                entity_ids[0]: [
                    {
                        "state": "unavailable",
                        "last_changed": start.isoformat(),
                        "attributes": {"unit_of_measurement": "W"},
                    },
                    {"state": "1000", "last_changed": (start + timedelta(seconds=1)).isoformat()},
                ]
            }

        config = {
            "timezone": "Europe/Stockholm",
            "input_sensors": {"load_power": "sensor.load"},
        }
        with (
            patch(
                "backend.core.ha_client.secrets.load_home_assistant_config",
                return_value={"url": "http://ha.local", "token": "tok"},
            ),
            patch.object(ha_client, "get_power_history_batch", AsyncMock(side_effect=fake_history)),
        ):
            profile = await ha_client.get_load_profile_from_ha(config)

        assert len(profile) == 96
        # Constant 1 kW is 24 kWh/day: slots are averaged over their valid time, so the
        # 1 s `unavailable` lead of each chunk is excluded, not counted as zero load
        # (the old divide-by-7 gave 24 - 1/3600). The 1000x unit bug would give 24000.
        assert sum(profile) == pytest.approx(24.0, abs=1e-9)
