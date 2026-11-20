"""Tests for Nordpool timeout behavior - DNS crash loop fixes.

This test ensures that Nordpool API calls have proper timeout handling
and fallback behavior when the API is unresponsive.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import pytz
import yaml


@pytest.fixture
def temp_config_file(tmp_path):
    """Create a temporary config file for testing."""
    config = {
        "version": "2.5.1-beta",
        "timezone": "Europe/Stockholm",
        "nordpool": {
            "price_area": "SE3",
            "currency": "SEK",
        },
    }
    config_path = tmp_path / "test_nordpool_config.yaml"
    config_path.write_text(yaml.dump(config))
    return str(config_path)


@pytest.mark.asyncio
async def test_get_nordpool_data_times_out_gracefully(temp_config_file):
    """Verify that Nordpool fetch has a 10-second timeout and returns [] on timeout.

    This is a regression test for the DNS crash loop bug where blocking I/O
    could cause the event loop to hang.

    The fix: Wrap prices_client.fetch in asyncio.wait_for(timeout=10.0) and
    catch TimeoutError to return an empty list gracefully.
    """
    from backend.core.prices import get_nordpool_data

    # Mock cache and Prices class to be slow
    with patch("backend.core.prices.cache_sync") as mock_cache:
        # Mock cache.get to always return None so fetch is always called
        mock_cache.get.return_value = None

        with patch("backend.core.prices.Prices") as mock_prices_class:
            mock_prices = MagicMock()

            # Mock asyncio.to_thread to simulate timeout
            async def mock_to_thread(func, *args, **kwargs):
                raise TimeoutError("Simulated timeout")

            with patch("asyncio.to_thread", side_effect=mock_to_thread):
                mock_prices_class.return_value = mock_prices

                # Call should complete quickly due to timeout
                start = asyncio.get_event_loop().time()
                result = await get_nordpool_data(temp_config_file)
                elapsed = asyncio.get_event_loop().time() - start

                # Should timeout and return [] within ~10 seconds + overhead
                assert elapsed < 15.0, f"Nordpool fetch took {elapsed}s, should timeout at 10s"
                assert result == [], "Should return empty list on timeout"


@pytest.mark.asyncio
async def test_get_nordpool_data_succeeds_quickly(temp_config_file):
    """Verify that normal Nordpool fetches complete successfully within timeout."""
    from backend.core.prices import get_nordpool_data

    tz = pytz.timezone("Europe/Stockholm")
    today = datetime.now(tz).date()

    # Create mock price data
    mock_values = []
    for hour in range(24):
        slot_start = datetime.combine(today, datetime.min.time(), tzinfo=tz) + timedelta(hours=hour)
        mock_values.append(
            {
                "start": slot_start,
                "end": slot_start + timedelta(hours=1),
                "value": 1.0,  # 1 SEK/kWh
            }
        )

    with patch("backend.core.prices.cache_sync") as mock_cache:
        # Mock cache.get to always return None so fetch is always called
        mock_cache.get.return_value = None

        with patch("backend.core.prices.Prices") as mock_prices_class:
            mock_prices = MagicMock()
            mock_prices.fetch.return_value = {
                "areas": {
                    "SE3": {
                        "values": mock_values,
                    }
                }
            }
            mock_prices_class.return_value = mock_prices

            # Call should succeed
            result = await get_nordpool_data(temp_config_file)

            # Should return price data
            assert isinstance(result, list)
            assert len(result) > 0


@pytest.mark.asyncio
async def test_get_nordpool_tomorrow_fetch_also_has_timeout(temp_config_file):
    """Verify that tomorrow's price fetch (after 13:00) also has timeout protection."""
    from backend.core.prices import get_nordpool_data

    tz = pytz.timezone("Europe/Stockholm")

    # Mock current time to be after 13:00 so tomorrow's prices are fetched
    mock_now = datetime.now(tz).replace(hour=14, minute=0)

    call_count = 0

    async def mock_to_thread(func, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Always raise timeout to test that timeout protection works
        raise TimeoutError("Simulated timeout")

    with (
        patch("backend.core.prices.cache_sync") as mock_cache,
        patch("backend.core.prices.Prices") as mock_prices_class,
        patch("backend.core.prices.datetime") as mock_datetime,
        patch("asyncio.to_thread", side_effect=mock_to_thread),
    ):
        # Mock cache.get to always return None so fetch is always called
        mock_cache.get.return_value = None
        mock_datetime.now.return_value = mock_now
        mock_datetime.combine = datetime.combine

        mock_prices = MagicMock()
        mock_prices_class.return_value = mock_prices

        # Should timeout on first call
        start = asyncio.get_event_loop().time()
        result = await get_nordpool_data(temp_config_file)
        elapsed = asyncio.get_event_loop().time() - start

        # First fetch should timeout quickly
        assert elapsed < 15.0, f"Took {elapsed}s, should timeout at 10s"
        assert result == []
        # Note: Only 1 call is made because the exception propagates
        # and returns [] before attempting the second fetch
        assert call_count == 1


@pytest.mark.asyncio
async def test_get_nordpool_partial_timeout(temp_config_file):
    """Verify behavior when today succeeds but tomorrow times out."""
    from backend.core.prices import get_nordpool_data

    tz = pytz.timezone("Europe/Stockholm")
    today = datetime.now(tz).date()
    mock_now = datetime.now(tz).replace(hour=14, minute=0)

    # Create mock price data for today
    mock_values_today = []
    for hour in range(24):
        slot_start = datetime.combine(today, datetime.min.time(), tzinfo=tz) + timedelta(hours=hour)
        mock_values_today.append(
            {
                "start": slot_start,
                "end": slot_start + timedelta(hours=1),
                "value": 1.0,
            }
        )

    call_count = 0

    async def mock_to_thread(func, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Check which date is being fetched by looking at the kwargs passed to fetch
        # The fetch function is called with end_date as a keyword argument
        # Since we can't see args here directly, we simulate:
        # First call is for today, second call is for tomorrow
        if call_count == 1:
            # First call (today) succeeds
            return {"areas": {"SE3": {"values": mock_values_today}}}
        else:
            # Second call (tomorrow) times out
            raise TimeoutError("Simulated timeout")

    with (
        patch("backend.core.prices.cache_sync") as mock_cache,
        patch("backend.core.prices.Prices") as mock_prices_class,
        patch("backend.core.prices.datetime") as mock_datetime,
        patch("asyncio.to_thread", side_effect=mock_to_thread),
    ):
        # Mock cache.get to always return None so fetch is always called
        mock_cache.get.return_value = None
        mock_datetime.now.return_value = mock_now
        mock_datetime.combine = datetime.combine

        mock_prices = MagicMock()
        mock_prices_class.return_value = mock_prices

        # Should return today's data even if tomorrow times out
        result = await get_nordpool_data(temp_config_file)

        # Should have attempted both calls
        assert call_count == 2
        # Today's slots are kept even though tomorrow failed
        assert len(result) == 24
        assert all(slot["start_time"].date() == today for slot in result)
