"""Tests for per-event-loop HA HTTP client management."""

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from backend.core import ha_client
from backend.core.ha_client import (
    close_ha_http_client,
    get_ha_http_client,
    get_ha_entity_state,
)


@pytest.mark.asyncio
async def test_client_singleton_reuse_within_loop():
    """Within one event loop, get_ha_http_client returns the same instance each call."""
    client1 = get_ha_http_client()
    client2 = get_ha_http_client()
    assert client1 is client2
    assert isinstance(client1, httpx.AsyncClient)


@pytest.mark.asyncio
async def test_client_close():
    """After close_ha_http_client, the old client is closed and a new one is created."""
    client = get_ha_http_client()
    assert not client.is_closed

    await close_ha_http_client()
    assert client.is_closed

    # Accessing again should recreate a fresh client
    client_new = get_ha_http_client()
    assert client_new is not client
    assert not client_new.is_closed


def test_cross_loop_isolation():
    """Clients obtained from two separate event loops must be distinct instances.

    This is the core regression test for the concurrency bug: two asyncio.run()
    calls create two distinct event loops.  Without the per-loop fix the shared
    singleton would be bound to the first loop and raise RuntimeError on the
    second.  With the fix each loop gets its own client.
    """
    results: list[httpx.AsyncClient] = []

    async def grab_client() -> httpx.AsyncClient:
        return get_ha_http_client()

    # Two separate asyncio.run calls → two distinct event loops
    client_a = asyncio.run(grab_client())
    client_b = asyncio.run(grab_client())

    results.extend([client_a, client_b])

    # Each loop gets its own client (different objects)
    assert client_a is not client_b, (
        "Each event loop must receive a distinct client; "
        "sharing would raise 'Future bound to a different event loop'"
    )
    # Both must be functional (not closed)
    assert not client_a.is_closed
    assert not client_b.is_closed


@pytest.mark.asyncio
async def test_get_entity_state_preserves_error_behavior():
    """get_ha_entity_state returns None and does not raise on connection errors."""
    with patch("backend.core.secrets.load_home_assistant_config") as mock_load:
        mock_load.return_value = {"url": "http://mock-ha", "token": "mock-token"}

        client = get_ha_http_client()
        with patch.object(client, "get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = httpx.ConnectError("Connection refused")
            state = await get_ha_entity_state("sensor.power")
            assert state is None
            mock_get.assert_called_once()
            # Assert timeout of 10s was passed
            assert mock_get.call_args[1]["timeout"] == 10.0
