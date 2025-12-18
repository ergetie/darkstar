import sys
import yaml
import pymysql
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
    print("🔍 Checking MariaDB Consumption (Nov 24-30)...")
    secrets = load_secrets()

    try:
        with connect_db(secrets) as conn:
            with conn.cursor() as cur:
                query = """
                    SELECT 
                        SUM(grid_import_kwh) as total_import,
                        SUM(actual_load_kwh) as total_load,
                        COUNT(*) as slots
                    FROM execution_history 
                    WHERE slot_start BETWEEN '2025-11-24 00:00:00' AND '2025-11-30 23:59:59'
                """
                cur.execute(query)
                res = cur.fetchone()

                print(f"   Slots: {res['slots']}")
                print(f"   Total Import: {res['total_import']} kWh")
                print(f"   Total Load:   {res['total_load']} kWh")

                user_import = 258.0
                db_import = float(res["total_import"] or 0.0)

                print(f"\n   User Import: {user_import}")
                print(f"   DB Import:   {db_import}")
                print(f"   Diff:        {db_import - user_import}")

    except Exception as e:
        print(f"❌ Check failed: {e}")


if __name__ == "__main__":
    main()
