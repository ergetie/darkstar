"""Last plan save outcome for the slot_plans table.

The pipeline treats a failed ``store_plan`` as non-fatal (``schedule.json`` is
already written and the executor only needs that), so the failure is recorded
here and surfaced by ``HealthChecker.check_planner`` as a warning until a later
save succeeds. In-process only: a restart clears it, and the next planner run
records it again if the fault persists.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class PlanStoreFailure:
    summary: str
    failed_at: datetime


_lock = threading.Lock()
_last_failure: PlanStoreFailure | None = None


def record_plan_store_failure(error: BaseException) -> None:
    """Record a failed plan save, replacing any earlier failure."""
    global _last_failure
    summary = f"{type(error).__name__}: {error}"
    with _lock:
        _last_failure = PlanStoreFailure(summary=summary, failed_at=datetime.now(UTC))


def clear_plan_store_failure() -> None:
    """Clear the recorded failure after a successful plan save."""
    global _last_failure
    with _lock:
        _last_failure = None


def get_plan_store_failure() -> PlanStoreFailure | None:
    """Return the current plan save failure, or None if the last save succeeded."""
    with _lock:
        return _last_failure
