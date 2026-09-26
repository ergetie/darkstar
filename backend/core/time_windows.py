"""Reusable local-time window matcher.

A time window selects wall-clock slots by month, weekday and hour range. It is
used by time-of-use transfer fees and is designed to be reused by other
features that need "which hours count" semantics (e.g. a future peak guard).

Semantics:
- ``months``: list of 1-12; omitted/empty matches every month.
- ``weekdays``: list of 0-6 (0=Mon .. 6=Sun, Python ``weekday()``); omitted/empty
  matches every day.
- ``hours``: ``{start, end}`` half-open local-hour range ``[start, end)`` with
  ``0 <= start <= 23``, ``1 <= end <= 24`` and ``start != end``. ``start > end``
  wraps past midnight. Omitted matches the whole day.

When ``holidays_as_weekend`` is enabled, Swedish public holidays (plus the
de-facto non-working eves) are treated as weekend days: a weekday filter
matches them only if it includes Saturday (5) or Sunday (6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any, cast

SATURDAY = 5
SUNDAY = 6


@dataclass(frozen=True)
class TimeWindow:
    """A parsed, validated local-time window."""

    months: frozenset[int] = frozenset()
    weekdays: frozenset[int] = frozenset()
    hour_start: int | None = None
    hour_end: int | None = None


def _parse_int_list(raw: Any, field: str, lo: int, hi: int) -> frozenset[int]:
    if raw is None:
        return frozenset()
    if not isinstance(raw, list):
        raise ValueError(f"{field} must be a list")
    values: set[int] = set()
    for item in cast("list[Any]", raw):
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError(f"{field} values must be integers {lo}-{hi}")
        if not lo <= item <= hi:
            raise ValueError(f"{field} value {item} is outside {lo}-{hi}")
        values.add(item)
    return frozenset(values)


def _parse_hour(raw: Any, field: str, lo: int, hi: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"hours.{field} must be an integer {lo}-{hi}")
    if not lo <= raw <= hi:
        raise ValueError(f"hours.{field} {raw} is outside {lo}-{hi}")
    return raw


def parse_window(raw: Any) -> TimeWindow:
    """Parse a window dict. Raises ``ValueError`` on invalid input."""
    if not isinstance(raw, dict):
        raise ValueError("window must be a mapping")
    window = cast("dict[str, Any]", raw)
    months = _parse_int_list(window.get("months"), "months", 1, 12)
    weekdays = _parse_int_list(window.get("weekdays"), "weekdays", 0, 6)
    hours: Any = window.get("hours")
    if hours is None:
        return TimeWindow(months=months, weekdays=weekdays)
    if not isinstance(hours, dict):
        raise ValueError("hours must be a mapping with start and end")
    hour_range = cast("dict[str, Any]", hours)
    start = _parse_hour(hour_range.get("start"), "start", 0, 23)
    end = _parse_hour(hour_range.get("end"), "end", 1, 24)
    if start == end:
        raise ValueError("hours.start and hours.end must differ")
    return TimeWindow(months=months, weekdays=weekdays, hour_start=start, hour_end=end)


def _easter_sunday(year: int) -> date:
    """Anonymous Gregorian computus (Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month, day = divmod(h + ll - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _saturday_between(start: date) -> date:
    """First Saturday on or after ``start`` (used for 7-day floating holidays)."""
    return start + timedelta(days=(SATURDAY - start.weekday()) % 7)


@lru_cache(maxsize=32)
def swedish_public_holidays(year: int) -> frozenset[date]:
    """Swedish public holidays plus Midsommarafton, Julafton and Nyårsafton."""
    easter = _easter_sunday(year)
    midsummer_day = _saturday_between(date(year, 6, 20))
    return frozenset(
        {
            date(year, 1, 1),  # Nyårsdagen
            date(year, 1, 6),  # Trettondedag jul
            easter - timedelta(days=2),  # Långfredagen
            easter,  # Påskdagen
            easter + timedelta(days=1),  # Annandag påsk
            date(year, 5, 1),  # Första maj
            easter + timedelta(days=39),  # Kristi himmelsfärdsdag
            date(year, 6, 6),  # Sveriges nationaldag
            easter + timedelta(days=49),  # Pingstdagen
            midsummer_day - timedelta(days=1),  # Midsommarafton
            midsummer_day,  # Midsommardagen
            _saturday_between(date(year, 10, 31)),  # Alla helgons dag
            date(year, 12, 24),  # Julafton
            date(year, 12, 25),  # Juldagen
            date(year, 12, 26),  # Annandag jul
            date(year, 12, 31),  # Nyårsafton
        }
    )


def _weekday_matches(weekdays: frozenset[int], local_dt: datetime, holidays: bool) -> bool:
    if not weekdays:
        return True
    day = local_dt.date()
    if holidays and day in swedish_public_holidays(day.year):
        return SATURDAY in weekdays or SUNDAY in weekdays
    return local_dt.weekday() in weekdays


def _hour_matches(window: TimeWindow, hour: int) -> bool:
    if window.hour_start is None or window.hour_end is None:
        return True
    if window.hour_start < window.hour_end:
        return window.hour_start <= hour < window.hour_end
    return hour >= window.hour_start or hour < window.hour_end


def matches(window: TimeWindow, local_dt: datetime, holidays_as_weekend: bool = False) -> bool:
    """Return True if the local wall-clock datetime falls inside the window."""
    if window.months and local_dt.month not in window.months:
        return False
    if not _weekday_matches(window.weekdays, local_dt, holidays_as_weekend):
        return False
    return _hour_matches(window, local_dt.hour)
