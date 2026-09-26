"""Shared EV goal ready-by resolution (used by planner, API, and HA sync).

Single source of truth for turning a goal dict into the next ready-by
deadline, replacing the three copies that previously diverged (different
``every_n_days`` anchors, different ``repeat`` normalization).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytz


def _parse_hhmm(value: Any) -> tuple[int, int] | None:
    if value is None or value == "":
        return None
    txt = str(value).strip()
    try:
        hour_str, minute_str = txt.split(":")
        hour = int(hour_str)
        minute = int(minute_str)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return (hour, minute)
    except (ValueError, AttributeError):
        pass
    return None


def resolve_next_ready_by(
    goal: dict[str, Any], now: datetime, tz: pytz.BaseTzInfo
) -> datetime | None:
    """Resolve the next ready-by datetime for a goal dict.

    ``goal`` keys:
      - ``ready_by``: ``"HH:MM"`` string. Missing/unparseable -> ``None``.
      - ``repeat``: ``daily``/``weekdays``/``weekends``/``every_n_days``/``none``.
        Missing or ``None`` is treated as ``"daily"``.
      - ``ready_by_date``: ``YYYY-MM-DD``, required when ``repeat == "none"``;
        a past resulting deadline returns ``None`` (inert one-off).
      - ``n_days``: int >= 1, used by ``every_n_days`` (default 1).
      - ``anchor_date``: ``YYYY-MM-DD`` anchoring ``every_n_days`` cycles. Legacy
        goals without it fall back to the local date of ``last_updated``, then
        to ``now`` (see :func:`every_n_days_anchor`).
    """
    time_tuple = _parse_hhmm(goal.get("ready_by"))
    if time_tuple is None:
        return None
    hour, minute = time_tuple

    if now.tzinfo is None:
        now = tz.localize(now)

    repeat_raw = goal.get("repeat")
    repeat = str(repeat_raw).lower() if repeat_raw else "daily"

    if repeat == "none":
        date_str = goal.get("ready_by_date")
        if not date_str:
            return None
        try:
            target_date = date.fromisoformat(str(date_str).strip())
        except (ValueError, TypeError):
            return None
        deadline = tz.localize(datetime.combine(target_date, time(hour, minute)))
        return deadline if deadline > now else None

    candidate = tz.localize(datetime.combine(now.date(), time(hour, minute)))
    if candidate <= now:
        candidate += timedelta(days=1)

    if repeat == "daily":
        return candidate

    if repeat == "weekdays":
        while candidate.weekday() >= 5:  # 5=Saturday, 6=Sunday
            candidate += timedelta(days=1)
        return candidate

    if repeat == "weekends":
        while candidate.weekday() < 5:
            candidate += timedelta(days=1)
        return candidate

    if repeat == "every_n_days":
        n, anchor_date = _every_n_days_params(goal, now, tz)

        days_since_anchor = (now.date() - anchor_date).days
        next_idx = ((days_since_anchor // n) + 1) * n
        target_date = anchor_date + timedelta(days=next_idx)
        deadline = tz.localize(datetime.combine(target_date, time(hour, minute)))
        while deadline <= now:
            next_idx += n
            target_date = anchor_date + timedelta(days=next_idx)
            deadline = tz.localize(datetime.combine(target_date, time(hour, minute)))
        return deadline

    # Unknown repeat mode: behave like daily.
    return candidate


def every_n_days_anchor(goal: dict[str, Any], tz: pytz.BaseTzInfo) -> date | None:
    """The ``every_n_days`` cycle anchor of a goal, or ``None`` if underivable.

    The stable ``anchor_date`` field wins. Legacy goals without it fall back to
    the local date of ``last_updated``; callers that write the goal persist
    that value as ``anchor_date`` so later ``last_updated`` rewrites (HA echoes,
    reconnect adoption) never move the cycle.
    """
    anchor_raw = goal.get("anchor_date")
    if anchor_raw:
        try:
            return date.fromisoformat(str(anchor_raw).strip())
        except (ValueError, TypeError):
            pass
    updated_raw = goal.get("last_updated")
    if updated_raw:
        try:
            updated = datetime.fromisoformat(str(updated_raw))
        except (ValueError, TypeError):
            return None
        return updated.astimezone(tz).date() if updated.tzinfo else updated.date()
    return None


def _every_n_days_params(
    goal: dict[str, Any], now: datetime, tz: pytz.BaseTzInfo
) -> tuple[int, date]:
    n_days_raw = goal.get("n_days")
    n = n_days_raw if (isinstance(n_days_raw, int) and n_days_raw > 0) else 1
    anchor_date = every_n_days_anchor(goal, tz) or now.date()
    return n, anchor_date


def backfill_anchor_date(goal: dict[str, Any], tz: pytz.BaseTzInfo) -> None:
    """Persist the legacy ``last_updated`` anchor as ``anchor_date`` (in place).

    Only for ``every_n_days`` goals without an ``anchor_date``; locks the
    cycle as it currently resolves. Call before rewriting ``last_updated``.
    """
    if str(goal.get("repeat") or "").lower() != "every_n_days" or goal.get("anchor_date"):
        return
    anchor = every_n_days_anchor(goal, tz)
    if anchor is not None:
        goal["anchor_date"] = anchor.isoformat()


def resolve_previous_ready_by(
    goal: dict[str, Any], now: datetime, tz: pytz.BaseTzInfo
) -> datetime | None:
    """Resolve the most recent ready-by at or before ``now`` for a goal dict.

    Mirror of :func:`resolve_next_ready_by` (same keys and ``repeat``
    semantics): an occurrence that ``resolve_next_ready_by`` would have
    returned earlier and that has since passed. Used by the missed-goal grace
    window. ``repeat == "none"`` returns the one-off deadline once it has
    passed, else ``None``.
    """
    time_tuple = _parse_hhmm(goal.get("ready_by"))
    if time_tuple is None:
        return None
    hour, minute = time_tuple

    if now.tzinfo is None:
        now = tz.localize(now)

    repeat_raw = goal.get("repeat")
    repeat = str(repeat_raw).lower() if repeat_raw else "daily"

    if repeat == "none":
        date_str = goal.get("ready_by_date")
        if not date_str:
            return None
        try:
            target_date = date.fromisoformat(str(date_str).strip())
        except (ValueError, TypeError):
            return None
        deadline = tz.localize(datetime.combine(target_date, time(hour, minute)))
        return deadline if deadline <= now else None

    n, anchor_date = (
        _every_n_days_params(goal, now, tz) if repeat == "every_n_days" else (1, now.date())
    )

    def _is_occurrence(d: date) -> bool:
        if repeat == "weekdays":
            return d.weekday() < 5
        if repeat == "weekends":
            return d.weekday() >= 5
        if repeat == "every_n_days":
            # resolve_next_ready_by schedules anchor + k*n for k >= 1.
            offset = (d - anchor_date).days
            return offset >= n and offset % n == 0
        return True  # daily and unknown modes

    for back in range(max(7, n) + 1):
        d = now.date() - timedelta(days=back)
        if not _is_occurrence(d):
            continue
        candidate = tz.localize(datetime.combine(d, time(hour, minute)))
        if candidate <= now:
            return candidate
    return None


def apply_ha_ready_by(goal: dict[str, Any], ready_by_dt: datetime) -> bool:
    """Adopt an HA ready-by datetime into a goal dict (in place): always one-off.

    Shared by the HA live-change and reconnect-adoption paths so both produce
    identical goals (ha-schedule-sync): ``repeat: "none"``, ``ready_by_date``
    = the datetime's date and ``ready_by`` = its ``HH:MM``. A previous
    repeating mode is replaced and its ``anchor_date`` dropped. ``ready_by_dt``
    must already be in the local timezone. Returns True when anything changed.
    """
    ready_by_val = f"{ready_by_dt.hour:02d}:{ready_by_dt.minute:02d}"
    date_val = ready_by_dt.date().isoformat()
    if (
        goal.get("ready_by") == ready_by_val
        and goal.get("repeat") == "none"
        and goal.get("ready_by_date") == date_val
    ):
        return False
    goal["ready_by"] = ready_by_val
    goal["repeat"] = "none"
    goal["ready_by_date"] = date_val
    goal.pop("anchor_date", None)
    return True


def stamp_ha_goal_update(goal: dict[str, Any], now: datetime, tz: pytz.BaseTzInfo) -> None:
    """Mark a goal as changed from HA (in place) without moving the every-N-days cycle.

    Persists a legacy ``anchor_date`` before ``last_updated`` is rewritten
    (HA sync never derives a new anchor), then sets ``source``/``last_updated``.
    Never touches ``repeat``.
    """
    backfill_anchor_date(goal, tz)
    goal.setdefault("keep_on_after_target", False)
    goal["source"] = "ha"
    goal["last_updated"] = now.isoformat()
