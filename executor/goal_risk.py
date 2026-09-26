"""
Goal-at-risk classification for load-balancer pause notifications
(load-balancer-graceful-degradation D7).

Pure logic: the engine passes the charger's persisted goal (from
data/ev_multi_day_state.json), the planner's ``meta.ev_goal_diagnostics`` and
the current slot's planned kW for the charger.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

# A pause inside a goal-scheduled slot this close to the deadline is at risk
# regardless of what the (possibly optimistic) diagnostics say.
GOAL_DEADLINE_RISK_WINDOW = timedelta(hours=2)
# Matches planner.pipeline.EV_SHORTFALL_EPS_KWH.
_SHORTFALL_EPS_KWH = 0.01
# Planned kW above this counts as goal-scheduled charging (matches the
# executor's "charger_plan_kw > 0.1" convention).
_PLANNED_KW_EPS = 0.1


def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pause_puts_goal_at_risk(
    goal: dict[str, Any] | None,
    diagnostics: dict[str, Any] | None,
    slot_planned_kw: float,
    now: datetime,
) -> tuple[bool, str]:
    """Return (at_risk, why) for a balancer pause of one charger.

    - No active goal (deadline in the future and positive required energy):
      not at risk.
    - Diagnostics stale (goal edited after the last plan, or a different
      deadline): at risk — fail open so a real risk is never suppressed.
    - Diagnostics report a shortfall: at risk.
    - The slot plans goal charging and the deadline is within 2 h: at risk.
    - No diagnostics entry in a plan newer than the goal: the planner
      deliberately skipped the charger (e.g. stale SoC, which notifies on its
      own): not at risk.
    """
    if not goal:
        return False, "no goal"
    deadline = _parse_dt(goal.get("deadline"))
    required = _float(goal.get("required_kwh"))
    if deadline is None or required is None or required <= 0 or deadline <= now:
        return False, "no active goal"

    goal_edited = _parse_dt(goal.get("last_updated"))
    planned_at = _parse_dt(goal.get("last_planned_at"))
    if goal_edited is not None and (planned_at is None or goal_edited > planned_at):
        return True, "goal changed since the last plan"

    if diagnostics:
        diag_deadline = _parse_dt(diagnostics.get("deadline"))
        if diag_deadline is None or diag_deadline != deadline:
            return True, "plan diagnostics are out of date"
        shortfall = _float(diagnostics.get("shortfall_kwh")) or 0.0
        if shortfall > _SHORTFALL_EPS_KWH or diagnostics.get("reason"):
            return True, f"plan already short by {shortfall:.1f} kWh"

    if slot_planned_kw > _PLANNED_KW_EPS and deadline - now <= GOAL_DEADLINE_RISK_WINDOW:
        minutes = int((deadline - now).total_seconds() // 60)
        return True, f"goal charging with the deadline in {minutes} min"

    return False, "goal on track"
