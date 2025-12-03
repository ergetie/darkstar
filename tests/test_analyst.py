import unittest
import unittest.mock
import sqlite3
import json
import json
import os
from datetime import datetime, timedelta, timezone
import pandas as pd
from backend.learning.analyst import Analyst

class TestAnalyst(unittest.TestCase):
    def setUp(self):
        self.test_db = "/tmp/debug_test.db"
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
            
        # Create schema
        with sqlite3.connect(self.test_db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS slot_observations (
                    slot_start TEXT PRIMARY KEY,
                    load_kwh REAL,
                    pv_kwh REAL,
                    battery_soc_percent REAL,
                    battery_kwh REAL,
                    created_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS slot_plans (
                    slot_start TEXT PRIMARY KEY,
                    load_forecast_kwh REAL,
                    pv_forecast_kwh REAL,
                    created_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS learning_daily_metrics (
                    date TEXT PRIMARY KEY,
                    pv_adjustment_by_hour_kwh TEXT,
                    load_adjustment_by_hour_kwh TEXT,
                    s_index_base_factor REAL,
                    updated_at TEXT
                )
            """)

    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def test_analyst_bias_detection(self):
        config = {
            "learning": {
                "enable": True,
                "auto_tune_enabled": True,
                "sqlite_path": self.test_db
            },
            "timezone": "UTC"
        }
        
        # Mock dataframes
        now_utc = datetime.now(timezone.utc)
        start = now_utc - timedelta(days=3)
        
        obs_data = []
        plans_data = []
        
        for i in range(24 * 3):
            t = start + timedelta(hours=1) * i
            t = t.replace(minute=0, second=0, microsecond=0)
            
            obs_data.append({
                "slot_start": t,
                "load_kwh": 1.5,
                "pv_kwh": 0.0
            })
            plans_data.append({
                "slot_start": t,
                "load_forecast_kwh": 1.0,
                "pv_forecast_kwh": 0.0
            })
            
        obs_df = pd.DataFrame(obs_data)
        plans_df = pd.DataFrame(plans_data)
        
        # Run Analyst with mocks
        with unittest.mock.patch.object(Analyst, '_fetch_observations', return_value=obs_df):
            with unittest.mock.patch.object(Analyst, '_fetch_plans', return_value=plans_df):
                analyst = Analyst(config)
                analyst.update_learning_overlays()
        
        # Verify Results in DB
        # The Analyst writes to learning_daily_metrics
        today_str = datetime.now().date().isoformat()
        
        with sqlite3.connect(self.test_db) as conn:
            cursor = conn.execute(
                "SELECT load_adjustment_by_hour_kwh FROM learning_daily_metrics WHERE date = ?", 
                (today_str,)
            )
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            
            adj = json.loads(row[0])
            # Bias = Actual (1.5) - Forecast (1.0) = +0.5
            # Adjustment should be +0.5
            self.assertAlmostEqual(adj[12], 0.5, places=1)
            self.assertAlmostEqual(adj[0], 0.5, places=1)

if __name__ == "__main__":
    unittest.main()
