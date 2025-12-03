import sys
import yaml
import pymysql
import pandas as pd
from pathlib import Path

# Add project root to path
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
    print("🔍 Inspecting MariaDB Prices (Today)...")
    secrets = load_secrets()
    
    try:
        with connect_db(secrets) as conn:
            with conn.cursor() as cur:
                # Get prices for today
                query = """
                    SELECT slot_start, import_price
                    FROM execution_history 
                    WHERE slot_start >= DATE(NOW())
                    ORDER BY slot_start ASC
                    LIMIT 20
                """
                cur.execute(query)
                rows = cur.fetchall()
                
                print(f"\n   Found {len(rows)} slots for today.")
                print(f"   {'Slot':<25} | {'Price':<10}")
                print("-" * 40)
                
                for row in rows:
                    print(f"   {row['slot_start']} | {row['import_price']}")

                # Check for variance within an hour
                if len(rows) >= 4:
                    p1 = rows[0]['import_price']
                    p2 = rows[1]['import_price']
                    p3 = rows[2]['import_price']
                    p4 = rows[3]['import_price']
                    
                    if p1 == p2 == p3 == p4:
                        print("\n⚠️  Prices appear to be HOURLY (first 4 slots are identical).")
                    else:
                        print("\n✅ Prices appear to be 15-MINUTE (variation detected).")

    except Exception as e:
        print(f"❌ Inspection failed: {e}")

if __name__ == "__main__":
    main()
