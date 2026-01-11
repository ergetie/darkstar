import datetime
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytz

# Ensure we can import from the root
sys.path.append(str(Path.cwd()))

from backend.core.cache import cache_sync
from inputs import get_nordpool_data


def test_poisoned_cache_invalidation():
    # Setup
    local_tz = pytz.timezone("Europe/Stockholm")
    now = datetime.datetime.now(local_tz).replace(hour=14, minute=0, second=0, microsecond=0)
    today = now.date()
    tomorrow = today + datetime.timedelta(days=1)

    # Poisoned cache: starts tomorrow
    poisoned_data = [
        {
            "start_time": local_tz.localize(
                datetime.datetime.combine(tomorrow, datetime.time(0, 0))
            ),
            "end_time": local_tz.localize(datetime.datetime.combine(tomorrow, datetime.time(1, 0))),
            "import_price_sek_kwh": 1.0,
            "export_price_sek_kwh": 0.9,
        }
    ]

    cache_sync.set("nordpool_data", poisoned_data, ttl_seconds=3600)

    # Mock config
    mock_config = {
        "timezone": "Europe/Stockholm",
        "nordpool": {"price_area": "SE4", "currency": "SEK", "resolution_minutes": 60},
        "pricing": {"vat_percent": 25.0, "grid_transfer_fee_sek": 0.2, "energy_tax_sek": 0.4},
    }

    with (
        patch("inputs.yaml.safe_load", return_value=mock_config),
        patch("inputs.Path.open", MagicMock()),
        patch("inputs.datetime") as mock_datetime,
        patch("inputs.Prices") as mock_prices,
    ):
        mock_datetime.now.return_value = now
        mock_datetime.combine = datetime.datetime.combine  # Restore combine

        # Mock Nordpool fetch to return something
        mock_client = MagicMock()
        mock_prices.return_value = mock_client
        mock_client.fetch.return_value = {
            "areas": {
                "SE4": {
                    "values": [
                        {"start": now, "end": now + datetime.timedelta(hours=1), "value": 1000.0}
                    ]
                }
            }
        }

        print(
            f"Running test at {now} with poisoned cache starting at {poisoned_data[0]['start_time']}"
        )

        # Call the function
        result = get_nordpool_data("dummy_config.yaml")

        # Verify
        assert result[0]["start_time"].date() == today, (
            f"Should have fetched today's data, but first slot is {result[0]['start_time']}"
        )
        print("Success: Cache was invalidated and today's data was fetched!")


if __name__ == "__main__":
    try:
        test_poisoned_cache_invalidation()
    except Exception as e:
        print(f"Test FAILED: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
