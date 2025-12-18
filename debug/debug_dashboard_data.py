import sys
import os
import logging
from datetime import datetime, timedelta
import pandas as pd
import json

# Add project root to path
sys.path.append(os.getcwd())

from backend.api.aurora import _fetch_horizon_series, _get_engine_and_config
from backend.learning.store import LearningStore

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def debug_dashboard_data():
    try:
        engine, config = _get_engine_and_config()

        print("\n=== 1. Testing Store Fetch Directly ===")
        # Mimic the call in aurora.py
        # df_pv = engine.store.get_forecast_vs_actual(days_back=2, target="pv")
        # We need to see what this returns

        days_back = 2

        # Manually run the query from store.py logic to see raw rows
        with open("backend/learning/store.py") as f:
            # Just reading to confirm logic? No, let's call the method if possible.
            pass

        if hasattr(engine, "store"):
            df_pv = engine.store.get_forecast_vs_actual(days_back=2, target="pv")
            print(f"Store returned {len(df_pv)} PV rows.")
            if not df_pv.empty:
                print("Sample PV Row:", df_pv.iloc[0].to_dict())
                print("Last PV Row:", df_pv.iloc[-1].to_dict())
            else:
                print("df_pv is EMPTY.")
        else:
            print("Engine has no store.")

        print("\n=== 2. Testing Aurora API Logic ===")
        # This calls _fetch_horizon_series but we modified aurora.py to add history *after* that function call
        # inside the /dashboard endpoint wrapper.
        # So we need to look at the code block I added in aurora.py (lines ~380+)

        # Let's verify what the timestamp logic does
        # slot_start calculation in aurora.py:
        # now = datetime.now(tz) ... minutes = (now.minute // 15) * 15 ...

        from backend.api.aurora import _get_timezone

        tz = getattr(engine, "timezone", _get_timezone())
        now = datetime.now(tz)
        minutes = (now.minute // 15) * 15
        slot_start = now.replace(minute=minutes, second=0, microsecond=0)
        if slot_start < now:
            slot_start += timedelta(minutes=15)

        print(f" calculated slot_start: {slot_start}")
        history_start_iso = (slot_start - timedelta(hours=24)).isoformat()
        print(f" filtering history >=: {history_start_iso}")

        if hasattr(engine, "store") and not df_pv.empty:
            # Check filtering
            # DB returns slot_start as string ISO usually
            print(f" DB slot_start type: {type(df_pv['slot_start'].iloc[0])}")
            print(f" DB slot_start sample: {df_pv['slot_start'].iloc[0]}")

            filtered = df_pv[df_pv["slot_start"] >= history_start_iso]
            print(f" Filtered rows ({len(filtered)})")
            if not filtered.empty:
                print(filtered[["slot_start", "actual"]].head())
            else:
                print(" Filtering removed all rows!")
                print(f" Comparison: '{df_pv['slot_start'].iloc[-1]}' vs '{history_start_iso}'")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    debug_dashboard_data()
