import json
import os
import random
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

from bin.run_planner import main as run_planner_main, load_yaml
import pytz
from ml.train import train_models



@dataclass
class SchedulerConfig:
    enabled: bool
    every_minutes: int
    jitter_minutes: int
    ml_training_enabled: bool = False
    ml_training_days: Tuple[int, ...] = ()
    ml_training_time: str = "03:00"
    timezone: str = "UTC"



@dataclass
class SchedulerStatus:
    enabled: bool
    every_minutes: int
    jitter_minutes: int
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None
    last_run_status: Optional[str] = None
    last_error: Optional[str] = None
    ml_training_last_run_at: Optional[str] = None



STATUS_PATH = Path("data") / "scheduler_status.json"


def _ensure_data_dir() -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_scheduler_config(config_path: str = "config.yaml") -> SchedulerConfig:
    cfg = load_yaml(config_path)
    automation = cfg.get("automation", {}) or {}
    enabled = bool(automation.get("enable_scheduler", False))
    schedule = automation.get("schedule", {}) or {}
    raw_every = schedule.get("every_minutes")
    raw_jitter = schedule.get("jitter_minutes", 0)

    try:
        every_minutes = int(raw_every)
    except (TypeError, ValueError):
        every_minutes = 60
    if every_minutes < 15:
        every_minutes = 15

    try:
        jitter_minutes = int(raw_jitter)
    except (TypeError, ValueError):
        jitter_minutes = 0
    if jitter_minutes < 0:
        jitter_minutes = 0

    # ML Training Config
    ml_cfg = automation.get("ml_training", {}) or {}
    ml_enabled = bool(ml_cfg.get("enabled", False))
    ml_days = tuple(ml_cfg.get("run_days", []))
    ml_time = str(ml_cfg.get("run_time", "03:00"))

    # System Timezone
    timezone_str = cfg.get("timezone", "UTC")

    return SchedulerConfig(
        enabled=enabled,
        every_minutes=every_minutes,
        jitter_minutes=jitter_minutes,
        ml_training_enabled=ml_enabled,
        ml_training_days=ml_days,
        ml_training_time=ml_time,
        timezone=timezone_str,
    )



def load_status() -> SchedulerStatus:
    _ensure_data_dir()
    if not STATUS_PATH.exists():
        cfg = load_scheduler_config()
        return SchedulerStatus(
            enabled=cfg.enabled,
            every_minutes=cfg.every_minutes,
            jitter_minutes=cfg.jitter_minutes,
        )

    try:
        with STATUS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception:
        cfg = load_scheduler_config()
        return SchedulerStatus(
            enabled=cfg.enabled,
            every_minutes=cfg.every_minutes,
            jitter_minutes=cfg.jitter_minutes,
        )

    cfg = load_scheduler_config()

    return SchedulerStatus(
        enabled=bool(data.get("enabled", cfg.enabled)),
        every_minutes=int(data.get("every_minutes", cfg.every_minutes)),
        jitter_minutes=int(data.get("jitter_minutes", cfg.jitter_minutes)),
        last_run_at=data.get("last_run_at"),
        next_run_at=data.get("next_run_at"),
        last_run_status=data.get("last_run_status"),
        last_error=data.get("last_error"),
        ml_training_last_run_at=data.get("ml_training_last_run_at"),
    )



def save_status(status: SchedulerStatus) -> None:
    _ensure_data_dir()
    payload: Dict[str, Any] = asdict(status)
    with STATUS_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _compute_next_run(from_time: datetime, every_minutes: int, jitter_minutes: int) -> datetime:
    base = from_time + timedelta(minutes=every_minutes)
    if jitter_minutes <= 0:
        return base
    jitter = random.randint(-jitter_minutes, jitter_minutes)
    return base + timedelta(minutes=jitter)


def _maybe_init_next_run(status: SchedulerStatus, cfg: SchedulerConfig) -> SchedulerStatus:
    if status.next_run_at:
        return status

    now = datetime.now(timezone.utc)
    if status.last_run_at:
        try:
            last = datetime.fromisoformat(status.last_run_at)
        except Exception:
            last = now
    else:
        last = now

    next_run = _compute_next_run(last, cfg.every_minutes, cfg.jitter_minutes)
    status.next_run_at = next_run.isoformat()
    status.enabled = cfg.enabled
    status.every_minutes = cfg.every_minutes
    status.jitter_minutes = cfg.jitter_minutes
    return status


def run_planner_once() -> Tuple[bool, Optional[str]]:
    try:
        code = run_planner_main()
        if code == 0:
            return True, None
        return False, f"Planner exited with code {code}"
    except Exception as exc:
        return False, str(exc)


from backend.learning.reflex import AuroraReflex

def run_reflex_once() -> Tuple[bool, Optional[str]]:
    try:
        reflex = AuroraReflex()
        report = reflex.run()
        print(f"[scheduler] Aurora Reflex Report: {report}")
        return True, None
    except Exception as exc:
        return False, str(exc)

def get_last_scheduled_time(
    run_days: Tuple[int, ...], run_time_str: str, timezone_str: str
) -> Optional[datetime]:
    """
    Calculate the most recent past occurrence of the schedule.
    run_days: List of integers (0=Monday, ... 6=Sunday).
    run_time_str: "HH:MM" 24h format.
    timezone_str: Timezone string (e.g. "Europe/Stockholm").
    """
    if not run_days:
        return None

    try:
        tz = pytz.timezone(timezone_str)
        now = datetime.now(tz)
        
        target_hour, target_minute = map(int, run_time_str.split(":"))
        
        # Check the last 14 days (covering 2 weeks) to find the most recent slot
        candidates = []
        for days_back in range(15):
            d = now - timedelta(days=days_back)
            if d.weekday() in run_days:
                # Construct the candidate time
                candidate = d.replace(
                    hour=target_hour, minute=target_minute, second=0, microsecond=0
                )
                if candidate <= now:
                    candidates.append(candidate)
        
        if not candidates:
            return None
            
        return max(candidates)

    except Exception:
        return None


def run_ml_training_task() -> Tuple[bool, Optional[str]]:
    """Safe wrapper for ML training task."""
    print("[scheduler] Starting ML Training Task...")
    try:
        # We run this in the same process since it's a synchronous blocking operation
        # for now, but in the future it might move to a subprocess.
        # Given train_models is blocking, this will pause the scheduler loop, which is fine
        # as training usually takes 10-60s on small datasets.
        train_models(days_back=90, min_samples=100)
        return True, None
    except Exception as exc:
        return False, str(exc)


def main() -> int:

    cfg = load_scheduler_config()
    status = load_status()
    status = _maybe_init_next_run(status, cfg)
    save_status(status)

    print(
        f"[scheduler] Starting with enabled={cfg.enabled}, "
        f"every={cfg.every_minutes}m, jitter={cfg.jitter_minutes}m"
    )

    last_reflex_run_date = None

    while True:
        time.sleep(30)

        cfg = load_scheduler_config()
        status = load_status()

        status.enabled = cfg.enabled
        status.every_minutes = cfg.every_minutes
        status.jitter_minutes = cfg.jitter_minutes



        # --- Aurora Reflex Daily Job (04:00 AM) ---
        now = datetime.now(timezone.utc)
        # Convert to local time for 4 AM check (assuming Europe/Stockholm from config, but simple check here)
        # We'll just use UTC for simplicity or rely on the fact that the machine is likely in local time or we want 4 AM UTC.
        # Let's assume 4 AM UTC for now to be safe.
        if now.hour == 4 and now.minute < 30:
            today_str = now.date().isoformat()
            if last_reflex_run_date != today_str:
                print("[scheduler] Running Daily Aurora Reflex...")
                run_reflex_once()
                last_reflex_run_date = today_str
        # ------------------------------------------

        # --- ML Training Catch-Up Logic ---
        if cfg.ml_training_enabled:

            # 1. Determine "Last Valid Slot"
            last_scheduled_slot = get_last_scheduled_time(
                cfg.ml_training_days, cfg.ml_training_time, cfg.timezone
            )

            if last_scheduled_slot:
                should_run = False
                
                # Check if we ever ran it
                if not status.ml_training_last_run_at:
                     should_run = True
                else:
                    try:
                        last_run_ts = datetime.fromisoformat(status.ml_training_last_run_at)
                        # Ensure timezone awareness for comparison
                        if last_run_ts.tzinfo is None:
                            # Assume UTC if stored without TZ, but that shouldn't happen with isoformat
                            last_run_ts = pytz.utc.localize(last_run_ts)
                        
                        # Compare
                        if last_run_ts < last_scheduled_slot:
                            should_run = True
                    except Exception:
                        should_run = True  # Corrupt state, safer to run

                if should_run:
                    print(
                        f"[scheduler] ML Training Catch-Up Triggered! "
                        f"Last slot: {last_scheduled_slot}, Last run: {status.ml_training_last_run_at}"
                    )
                    ml_ok, ml_err = run_ml_training_task()
                    
                    # Update status
                    if ml_ok:
                        now_utc = datetime.now(timezone.utc)
                        status.ml_training_last_run_at = now_utc.isoformat()
                        save_status(status)
                        print("[scheduler] ML Training Completed Successfully.")
                    else:
                        print(f"[scheduler] ML Training Failed: {ml_err}")
        # ----------------------------------

        if not cfg.enabled:

            save_status(status)
            continue

        try:
            next_run = datetime.fromisoformat(status.next_run_at) if status.next_run_at else now
        except Exception:
            next_run = now

        if now < next_run:
            continue

        started_at = datetime.now(timezone.utc)
        ok, error = run_planner_once()
        finished_at = datetime.now(timezone.utc)

        status.last_run_at = finished_at.isoformat()
        status.last_run_status = "success" if ok else "error"
        status.last_error = None if ok else error
        status.next_run_at = _compute_next_run(
            finished_at, cfg.every_minutes, cfg.jitter_minutes
        ).isoformat()

        save_status(status)
        print(
            "[scheduler] Run at "
            f"{started_at.isoformat()} -> {status.last_run_status}; next at {status.next_run_at}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
