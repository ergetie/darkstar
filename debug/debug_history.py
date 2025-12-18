import sys
import os
import logging
from datetime import datetime
import pandas as pd

# Add project root to path
sys.path.append(os.getcwd())

from backend.learning.store import LearningStore
from backend.api.aurora import _get_engine_and_config

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def debug_history():
    try:
        engine, config = _get_engine_and_config()
        if not hasattr(engine, "store"):
            print("Engine has no store!")
            return

        print(f"Store DB: {engine.store.db_path}")

        # Test PV fetch
        print("\n--- Fetching PV History (target='pv') ---")
        df_pv = engine.store.get_forecast_vs_actual(days_back=2, target="pv")
        print(f"Rows returned: {len(df_pv)}")
        if not df_pv.empty:
            print("Columns:", df_pv.columns.tolist())
            print(df_pv.head(3))
            print(df_pv.tail(3))
        else:
            print("No PV history found.")

        # Test Load fetch
        print("\n--- Fetching Load History (target='load') ---")
        df_load = engine.store.get_forecast_vs_actual(days_back=2, target="load")
        print(f"Rows returned: {len(df_load)}")
        if not df_load.empty:
            print("Columns:", df_load.columns.tolist())
            print(df_load.head(3))
        else:
            print("No Load history found.")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    debug_history()
