import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

# Configure logging
logging.basicConfig(level=logging.INFO)

from backend.learning.backfill import BackfillEngine


def main():
    print("🚀 Starting Manual Backfill...")
    try:
        engine = BackfillEngine("config.yaml")
        engine.run()
        print("✅ Backfill finished successfully.")
    except Exception as e:
        print(f"❌ Backfill failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
