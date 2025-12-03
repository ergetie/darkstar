import sys
import yaml
import pymysql
import pandas as pd
from datetime import datetime, timedelta

# Add project root to path
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

def load_secrets():
    try:
        with open("secrets.yaml", "r") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print("❌ secrets.yaml not found!")
        sys.exit(1)

def connect_db(secrets):
    db = secrets.get("mariadb", {})
    return pymysql.connect(
        host=db.get("host", "127.0.0.1"),
        port=int(db.get("port", 3306)),
        user=db.get("user"),
        password=db.get("password"),
        database=db.get("database"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )

def main():
    print("🔍 Inspecting MariaDB execution_history for Gaps & SoC...")
    secrets = load_secrets()
    
    try:
        with connect_db(secrets) as conn:
            with conn.cursor() as cur:
                # Check last 7 days
                print("\n📅 Checking last 7 days...")
                cur.execute("""
                    SELECT 
                        slot_start, 
                        actual_soc, 
                        planned_soc_projected,
                        import_price,
                        grid_import_kwh
                    FROM execution_history 
                    WHERE slot_start >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                    ORDER BY slot_start ASC
                """)
                rows = cur.fetchall()
                
                if not rows:
                    print("❌ No data in last 7 days!")
                    return

                df = pd.DataFrame(rows)
                print(f"   Total Rows: {len(df)}")
                
                # Check for NULLs
                null_actual = df['actual_soc'].isnull().sum()
                null_planned = df['planned_soc_projected'].isnull().sum()
                print(f"   NULL Actual SoC: {null_actual}")
                print(f"   NULL Planned SoC: {null_planned}")
                
                if null_planned > 0:
                    print("\n   Sample rows with NULL Planned SoC:")
                    print(df[df['planned_soc_projected'].isnull()].head(3))

                # Check for Time Gaps
                df['slot_start'] = pd.to_datetime(df['slot_start'])
                df['diff'] = df['slot_start'].diff()
                
                # Expected diff is 15 mins
                gaps = df[df['diff'] > timedelta(minutes=15)]
                print(f"\n   Time Gaps (>15m): {len(gaps)}")
                if len(gaps) > 0:
                    print("   Sample Gaps:")
                    print(gaps[['slot_start', 'diff']].head(5))

    except Exception as e:
        print(f"❌ Inspection failed: {e}")

if __name__ == "__main__":
    main()
