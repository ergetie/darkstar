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


@dataclass
class SchedulerConfig:
    enabled: bool
    every_minutes: int
    jitter_minutes: int


@dataclass
class SchedulerStatus:
    enabled: bool
    every_minutes: int
    jitter_minutes: int
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None
    last_run_status: Optional[str] = None
    last_error: Optional[str] = None


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

    return SchedulerConfig(
        enabled=enabled,
        every_minutes=every_minutes,
        jitter_minutes=jitter_minutes,
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


def main() -> int:
    cfg = load_scheduler_config()
    status = load_status()
    status = _maybe_init_next_run(status, cfg)
    save_status(status)

    print(
        f"[scheduler] Starting with enabled={cfg.enabled}, "
        f"every={cfg.every_minutes}m, jitter={cfg.jitter_minutes}m"
    )

    while True:
        time.sleep(30)

        cfg = load_scheduler_config()
        status = load_status()

        status.enabled = cfg.enabled
        status.every_minutes = cfg.every_minutes
        status.jitter_minutes = cfg.jitter_minutes

        if not cfg.enabled:
            save_status(status)
            continue

        now = datetime.now(timezone.utc)
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
