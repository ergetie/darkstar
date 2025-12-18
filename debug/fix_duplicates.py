import sys
import sqlite3
import logging
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from backend.learning import get_learning_engine
from backend.learning.backfill import BackfillEngine


def main():
    print("🧹 Cleaning up duplicates and re-syncing...")

    try:
        engine = get_learning_engine("config.yaml")

        # 1. Wipe Tables
        with sqlite3.connect(engine.db_path) as conn:
            print("   Deleting from slot_observations...")
            conn.execute("DELETE FROM slot_observations")

            print("   Deleting from slot_plans...")
            conn.execute("DELETE FROM slot_plans")

            conn.commit()
            print("   ✅ Tables wiped.")

        # 2. Run Backfill
        print("\n🚀 Starting Backfill...")
        backfill = BackfillEngine("config.yaml")
        backfill.run()
        print("   ✅ Backfill complete.")

    except Exception as e:
        print(f"❌ Fix failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
