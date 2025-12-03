import time
from datetime import datetime, timedelta, timezone

from backend.webapp import record_observation_from_current_state
from backend.learning.backfill import BackfillEngine


def _sleep_until_next_quarter() -> None:
    """Sleep until the next 15-minute boundary (UTC-based)."""
    now = datetime.now(timezone.utc)
    minute_block = (now.minute // 15) * 15
    current_slot = now.replace(minute=minute_block, second=0, microsecond=0)
    next_slot = current_slot + timedelta(minutes=15)
    sleep_seconds = max(5.0, (next_slot - now).total_seconds())
    time.sleep(sleep_seconds)


def main() -> int:
    """Background recorder loop: capture observations every 15 minutes."""
    print("[recorder] Starting live observation recorder (15m cadence)")

    # Run backfill on startup
    try:
        print("[recorder] Running startup backfill...")
        backfill = BackfillEngine()
        backfill.run()
    except Exception as e:
        print(f"[recorder] Backfill failed: {e}")

    # Run Analyst (Learning Loop) on startup
    try:
        from backend.learning.analyst import Analyst
        from inputs import load_home_assistant_config
        # We need the main config, but recorder doesn't load it directly usually.
        # Let's load it via inputs or just instantiate Analyst which loads its own store?
        # Analyst needs the full config dict.
        import yaml
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
            
        print("[recorder] Running Analyst (Learning Loop)...")
        analyst = Analyst(config)
        analyst.update_learning_overlays()
    except Exception as e:
        print(f"[recorder] Analyst failed: {e}")

    while True:
        try:
            record_observation_from_current_state()
        except Exception as exc:  # pragma: no cover - defensive logging
            print(f"[recorder] Error while recording observation: {exc}")

        _sleep_until_next_quarter()


if __name__ == "__main__":
    raise SystemExit(main())

