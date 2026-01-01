import os
import sys

try:
    import pymysql
except ImportError:
    print("Error: pymysql not installed.")
    print("Install with: pip install pymysql")
    sys.exit(1)

# Add root to path to import inputs
sys.path.append(os.getcwd())
from inputs import _load_yaml

def migrate():
    print("Starting DB migration check...")
    try:
        secrets = _load_yaml("secrets.yaml")
    except Exception as e:
        print(f"Failed to load secrets: {e}")
        return

    if not secrets or not secrets.get("mariadb"):
        print("No MariaDB configured in secrets.yaml.")
        return

    db = secrets["mariadb"]
    try:
        conn = pymysql.connect(
            host=db.get("host", "127.0.0.1"),
            port=int(db.get("port", 3306)),
            user=db.get("user"),
            password=db.get("password"),
            database=db.get("database"),
            autocommit=True
        )
    except Exception as e:
        print(f"Failed to connect to MariaDB: {e}")
        return
    
    with conn.cursor() as cur:
        # Check current_schedule
        try:
            cur.execute("SELECT planned_cost_sek FROM current_schedule LIMIT 1")
        except pymysql.err.OperationalError as e:
            if e.args[0] == 1054:
                print("Adding planned_cost_sek to current_schedule...")
                cur.execute("ALTER TABLE current_schedule ADD COLUMN planned_cost_sek FLOAT DEFAULT 0.0")
            else:
                print(f"Error checking current_schedule: {e}")
        except Exception as e:
             # Table might not exist or empty, handle gracefully
             print(f"Info checking current_schedule: {e}")
        
        # Check plan_history
        try:
            cur.execute("SELECT planned_cost_sek FROM plan_history LIMIT 1")
        except pymysql.err.OperationalError as e:
            if e.args[0] == 1054:
                print("Adding planned_cost_sek to plan_history...")
                cur.execute("ALTER TABLE plan_history ADD COLUMN planned_cost_sek FLOAT DEFAULT 0.0")
            else:
                print(f"Error checking plan_history: {e}")
        except Exception as e:
             print(f"Info checking plan_history: {e}")

    conn.close()
    print("Migration check complete.")

if __name__ == "__main__":
    migrate()
