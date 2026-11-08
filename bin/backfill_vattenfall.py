import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytz
import requests
import yaml

sys.path.insert(0, str(Path.cwd()))
from backend.core.prices import calculate_import_export_prices

# Constants
VATTENFALL_API = "https://www.vattenfall.se/api/price/spot/pricearea/{start}/{end}/{area}"


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as f:
        raw_data: Any = yaml.safe_load(f)
    return cast("dict[str, Any]", raw_data) if isinstance(raw_data, dict) else {}


def get_db_path(config: dict[str, Any]) -> str:
    return config.get("learning", {}).get("sqlite_path", "data/planner_learning.db")


def calculate_final_prices(
    spot_ore: float, config: dict[str, Any], slot_start: datetime | None = None
) -> tuple[float, float]:
    """
    Convert Spot (öre/kWh) to Import/Export (SEK/kWh) via the shared price formula.
    """
    spot_sek_mwh = spot_ore * 10.0  # öre/kWh -> SEK/MWh
    import_price, export_price = calculate_import_export_prices(
        spot_sek_mwh, config, slot_start=slot_start
    )
    return round(import_price, 4), round(export_price, 4)


def backfill_vattenfall(start_date_str: str, end_date_str: str, area: str = "SN4") -> None:
    config = load_config()
    db_path = get_db_path(config)
    tz = pytz.timezone(config.get("timezone", "Europe/Stockholm"))

    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date_str, "%Y-%m-%d").date()

    print(f"--- Backfilling Vattenfall ({area}) ---")
    print(f"Window: {start_dt} to {end_dt}")

    # Process in 30-day chunks
    current_start = start_dt
    total_slots = 0

    with sqlite3.connect(db_path) as conn:
        while current_start <= end_dt:
            current_end = min(current_start + timedelta(days=30), end_dt)

            # API format YYYY-MM-DD
            s_str = current_start.isoformat()
            e_str = current_end.isoformat()

            url = VATTENFALL_API.format(start=s_str, end=e_str, area=area)
            print(f"Fetching {s_str} to {e_str}...", end="", flush=True)

            try:
                headers = {"User-Agent": "DarkstarEnergyManager/1.0"}
                resp = requests.get(url, headers=headers, timeout=20)
                resp.raise_for_status()
                data: list[dict[str, Any]] = resp.json()

                rows_to_insert: list[tuple[str, str, float, float]] = []
                item: dict[str, Any]
                for item in data:
                    # Item: {"TimeStamp": "2025-08-01T00:00:00", "Value": 83.64, ...}

                    # Parse Time (Assuming Local Naive -> Localize)
                    ts_str = item.get("TimeStamp")
                    val_ore = item.get("Value")

                    if ts_str and val_ore is not None:
                        # Create naive datetime
                        dt_naive = datetime.fromisoformat(ts_str)
                        # Localize to configured timezone
                        dt_local = tz.localize(dt_naive)

                        # Calculate end time (1 hour later)
                        dt_end_local = dt_local + timedelta(hours=1)

                        # Calculate prices
                        imp, exp = calculate_final_prices(float(val_ore), config, dt_local)

                        rows_to_insert.append(
                            (dt_local.isoformat(), dt_end_local.isoformat(), imp, exp)
                        )

                if rows_to_insert:
                    conn.executemany(
                        """
                        INSERT INTO slot_observations
                        (slot_start, slot_end, import_price_sek_kwh, export_price_sek_kwh)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(slot_start) DO UPDATE SET
                        import_price_sek_kwh=excluded.import_price_sek_kwh,
                        export_price_sek_kwh=excluded.export_price_sek_kwh
                    """,
                        rows_to_insert,
                    )
                    conn.commit()
                    count = len(rows_to_insert)
                    total_slots += count
                    print(f" OK ({count} slots)")
                else:
                    print(" No data returned.")

            except Exception as e:
                print(f" Failed: {e}")

            # Move to next chunk
            current_start = current_end + timedelta(days=1)

    print(f"Done. Backfilled {total_slots} price slots.")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m bin.backfill_vattenfall YYYY-MM-DD YYYY-MM-DD [AREA]")
        exit(1)

    area_arg = sys.argv[3] if len(sys.argv) > 3 else "SN4"
    backfill_vattenfall(sys.argv[1], sys.argv[2], area_arg)
