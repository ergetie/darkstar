"""Unit tests for get_energy_from_power_history in ha_client."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytz

from backend.core.ha_client import get_energy_from_power_history


def _make_state(state_val: str, unit: str = "kW", ts: datetime | None = None) -> dict:
    if ts is None:
        ts = START
    return {
        "state": state_val,
        "last_changed": ts.isoformat(),
        "attributes": {"unit_of_measurement": unit},
    }


def _make_ha_config(url: str = "http://ha.local", token: str = "tok") -> dict:
    return {"url": url, "token": token}


START = datetime(2024, 1, 1, 10, 0, tzinfo=pytz.UTC)
END = START + timedelta(minutes=15)  # 0.25 hours


class TestGetEnergyFromPowerHistory:
    """Tests for get_energy_from_power_history."""

    @pytest.mark.asyncio
    async def test_step_integration_over_irregular_updates(self):
        """0 kW for 10 min, then 6 kW for 5 min -> 0.5 kWh."""
        states = [
            _make_state("0.0", ts=START),
            _make_state("6.0", ts=START + timedelta(minutes=10)),
        ]
        response_data = [states]

        with (
            patch(
                "backend.core.ha_client.secrets.load_home_assistant_config",
                return_value=_make_ha_config(),
            ),
            patch("backend.core.ha_client.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = response_data

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await get_energy_from_power_history("sensor.ev_power", START, END)

        assert result == pytest.approx(0.5, abs=0.001)

    @pytest.mark.asyncio
    async def test_single_sample_held_across_window(self):
        """Single 4 kW sample at the start is held for the full 15-minute window."""
        states = [_make_state("4.0", ts=START)]

        with (
            patch(
                "backend.core.ha_client.secrets.load_home_assistant_config",
                return_value=_make_ha_config(),
            ),
            patch("backend.core.ha_client.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = [states]

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await get_energy_from_power_history("sensor.ev_power", START, END)

        assert result == pytest.approx(1.0, abs=0.001)

    @pytest.mark.asyncio
    async def test_pre_window_state_clipped_to_window(self):
        """A state changed before the window is held from the window start."""
        states = [
            _make_state("2.0", ts=START - timedelta(minutes=2)),
            _make_state("5.0", ts=START + timedelta(minutes=9)),
        ]

        with (
            patch(
                "backend.core.ha_client.secrets.load_home_assistant_config",
                return_value=_make_ha_config(),
            ),
            patch("backend.core.ha_client.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = [states]

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await get_energy_from_power_history("sensor.ev_power", START, END)

        assert result == pytest.approx(0.8, abs=0.001)

    @pytest.mark.asyncio
    async def test_empty_response_returns_none(self):
        """Empty data list returns None."""
        with (
            patch(
                "backend.core.ha_client.secrets.load_home_assistant_config",
                return_value=_make_ha_config(),
            ),
            patch("backend.core.ha_client.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = []

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await get_energy_from_power_history("sensor.ev_power", START, END)

        assert result is None

    @pytest.mark.asyncio
    async def test_http_timeout_returns_none(self):
        """HTTP timeout exception returns None."""
        with (
            patch(
                "backend.core.ha_client.secrets.load_home_assistant_config",
                return_value=_make_ha_config(),
            ),
            patch("backend.core.ha_client.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await get_energy_from_power_history("sensor.ev_power", START, END)

        assert result is None

    @pytest.mark.asyncio
    async def test_connection_error_returns_none(self):
        """Connection error returns None."""
        with (
            patch(
                "backend.core.ha_client.secrets.load_home_assistant_config",
                return_value=_make_ha_config(),
            ),
            patch("backend.core.ha_client.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await get_energy_from_power_history("sensor.ev_power", START, END)

        assert result is None

    @pytest.mark.asyncio
    async def test_w_to_kw_normalization(self):
        """States in W are normalized to kW. 3000 W = 3 kW -> 0.75 kWh over 0.25h."""
        states = [_make_state("3000.0", unit="W", ts=START)]

        with (
            patch(
                "backend.core.ha_client.secrets.load_home_assistant_config",
                return_value=_make_ha_config(),
            ),
            patch("backend.core.ha_client.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = [states]

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await get_energy_from_power_history("sensor.ev_power", START, END)

        assert result == pytest.approx(0.75, abs=0.001)

    @pytest.mark.asyncio
    async def test_mixed_unavailable_states_hold_previous_valid_power(self):
        """unavailable/unknown samples do not reset the previous held power."""
        states = [
            _make_state("4.0", ts=START),
            _make_state("unknown", ts=START + timedelta(minutes=5)),
            _make_state("6.0", ts=START + timedelta(minutes=10)),
            _make_state("unavailable", ts=START + timedelta(minutes=12)),
        ]

        with (
            patch(
                "backend.core.ha_client.secrets.load_home_assistant_config",
                return_value=_make_ha_config(),
            ),
            patch("backend.core.ha_client.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = [states]

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await get_energy_from_power_history("sensor.ev_power", START, END)

        assert result == pytest.approx((4.0 * 10 / 60) + (6.0 * 5 / 60), abs=0.001)

    @pytest.mark.asyncio
    async def test_all_unavailable_returns_none(self):
        """All-unavailable state list returns None."""
        states = [_make_state("unavailable") for _ in range(5)]

        with (
            patch(
                "backend.core.ha_client.secrets.load_home_assistant_config",
                return_value=_make_ha_config(),
            ),
            patch("backend.core.ha_client.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = [states]

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await get_energy_from_power_history("sensor.ev_power", START, END)

        assert result is None

    @pytest.mark.asyncio
    async def test_missing_ha_config_returns_none(self):
        """Missing url/token returns None without HTTP call."""
        with patch(
            "backend.core.ha_client.secrets.load_home_assistant_config",
            return_value={},
        ):
            result = await get_energy_from_power_history("sensor.ev_power", START, END)

        assert result is None
