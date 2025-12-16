import time
import yaml
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


def _run_analyst() -> None:
    """Run the Learning Analyst to update s_index_base_factor and bias adjustments."""
    try:
        from backend.learning.analyst import Analyst
        
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
            
        print("[recorder] Running Analyst (Learning Loop)...")
        analyst = Analyst(config)
        analyst.update_learning_overlays()
    except Exception as e:
        print(f"[recorder] Analyst failed: {e}")


def main() -> int:
    """Background recorder loop: capture observations every 15 minutes."""
    print("[recorder] Starting live observation recorder (15m cadence)")

    # Load config for timezone
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
    tz_name = config.get("timezone", "Europe/Stockholm")
    
    import pytz
    tz = pytz.timezone(tz_name)

    # Run backfill on startup
    try:
        print("[recorder] Running startup backfill...")
        backfill = BackfillEngine()
        backfill.run()
    except Exception as e:
        print(f"[recorder] Backfill failed: {e}")

    # Run Analyst on startup
    _run_analyst()
    
    # Track last analyst run date to run once daily at ~6 AM local
    last_analyst_date = datetime.now(tz).date()

    while True:
        try:
            record_observation_from_current_state()
        except Exception as exc:  # pragma: no cover - defensive logging
            print(f"[recorder] Error while recording observation: {exc}")

        # Run Analyst once per day around 6 AM local time
        now_local = datetime.now(tz)
        if now_local.date() > last_analyst_date and now_local.hour >= 6:
            print(f"[recorder] Daily Analyst run triggered ({now_local.date()})")
            _run_analyst()
            last_analyst_date = now_local.date()

        _sleep_until_next_quarter()


if __name__ == "__main__":
    raise SystemExit(main())


