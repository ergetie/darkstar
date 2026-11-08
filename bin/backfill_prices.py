import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

import pytz
import yaml
from nordpool.elspot import Prices

sys.path.insert(0, str(Path.cwd()))
from learning import LearningEngine  # type: ignore[reportUnknownVariableType]

from backend.core.prices import calculate_import_export_prices


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as f:
        raw_data: Any = yaml.safe_load(f)
    return cast("dict[str, Any]", raw_data) if isinstance(raw_data, dict) else {}


def backfill_prices(days: int, config_path: str = "config.yaml") -> None:
    config = load_config(config_path)
    engine: Any = LearningEngine(config_path)  # type: ignore[assignment]

    nordpool_config: dict[str, Any] = config.get("nordpool", {}) or {}
    price_area: str = nordpool_config.get("price_area", "SE4")
    currency: str = nordpool_config.get("currency", "SEK")
    resolution_minutes: int = nordpool_config.get("resolution_minutes", 60)

    prices_client = Prices(currency)

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    print(f"Fetching prices from {start_date} to {end_date} for {price_area}...")

    # Nordpool library fetches by day. We iterate.
    current_date = start_date
    all_entries: list[dict[str, Any]] = []

    while current_date <= end_date:
        try:
            print(f"  Fetching {current_date}...")
            data: dict[str, Any] = prices_client.fetch(
                end_date=current_date, areas=[price_area], resolution=resolution_minutes
            )
            if data and data.get("areas") and data["areas"].get(price_area):
                values: list[Any] = data["areas"][price_area].get("values", [])
                all_entries.extend(values)
        except Exception as e:
            print(f"  Failed to fetch {current_date}: {e}")

        current_date += timedelta(days=1)

    if not all_entries:
        print("No data fetched.")
        return

    # Process and Store
    # Prices come from the shared formula (VAT, transfer fee rules, tax, supplier markup)
    local_tz = pytz.timezone(config.get("timezone", "Europe/Stockholm"))

    records: list[dict[str, Any]] = []
    entry: dict[str, Any]
    for entry in all_entries:
        start_time = entry["start"].astimezone(local_tz)
        end_time = entry["end"].astimezone(local_tz)

        import_price_sek_kwh, export_price_sek_kwh = calculate_import_export_prices(
            entry["value"], config, slot_start=start_time
        )

        records.append(
            {
                "start_time": start_time,
                "end_time": end_time,
                "import_price_sek_kwh": import_price_sek_kwh,
                "export_price_sek_kwh": export_price_sek_kwh,
            }
        )

    print(f"Storing {len(records)} price slots...")
    engine.store_slot_prices(records)  # type: ignore[method-call]
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill Nordpool prices")
    parser.add_argument("--days", type=int, default=7, help="Number of days to backfill")
    args = parser.parse_args()

    backfill_prices(args.days)
