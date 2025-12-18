import sys
import logging
from pathlib import Path
import json

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from backend.learning.backfill import BackfillEngine
from backend.learning import get_learning_engine

# Configure logging to stdout
logging.basicConfig(level=logging.INFO)


def main():
    print("🚀 Starting K7 Dry Run: The Mirror")

    # 1. Test Backfill
    print("\n🔄 Testing Backfill Engine...")
    try:
        backfill = BackfillEngine("config.yaml")
        # We won't actually fetch from HA to avoid auth errors in CI/DryRun,
        # but we can verify the class inits and run() handles "no data" gracefully.
        backfill.run()
        print("✅ Backfill run completed (check logs for details).")
    except Exception as e:
        print(f"❌ Backfill failed: {e}")
        sys.exit(1)

    # 2. Test Performance Metrics
    print("\n📊 Testing Performance Metrics API...")
    try:
        engine = get_learning_engine("config.yaml")
        data = engine.get_performance_series(days_back=7)

        soc_len = len(data.get("soc_series", []))
        cost_len = len(data.get("cost_series", []))

        print(f"✅ Retrieved {soc_len} SoC points and {cost_len} Cost points.")

        if soc_len > 0:
            print(f"   Sample SoC: {data['soc_series'][0]}")
        if cost_len > 0:
            print(f"   Sample Cost: {data['cost_series'][0]}")

    except Exception as e:
        print(f"❌ Metrics API failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
