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
      - ``last_updated``: ISO datetime string anchoring ``every_n_days`` cycles
        (falls back to ``now`` if absent/unparseable).
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
        n_days_raw = goal.get("n_days")
        n = n_days_raw if (isinstance(n_days_raw, int) and n_days_raw > 0) else 1

        anchor_date = now.date()
        anchor_str = goal.get("last_updated")
        if anchor_str:
            try:
                anchor_dt = datetime.fromisoformat(str(anchor_str))
                anchor_date = (
                    anchor_dt.astimezone(tz).date() if anchor_dt.tzinfo else anchor_dt.date()
                )
            except (ValueError, TypeError):
                pass

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
