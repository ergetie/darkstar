"""EV goal deferral value (ev-planning-model).

When an EV goal's deadline lies beyond the known-price horizon (the Kepler
slot list), the solver gets a tiered *deferral value*: a per-kWh price for
energy it leaves to post-horizon slots before the deadline. This module holds
the pure building blocks:

- classify the goal window into post-horizon slots and price each one
  (published spot > forecast ``spot_p50`` > trailing-average import price >
  maximum in-horizon import price);
- convert spot to import price with the same tariff as in-horizon prices;
- apply the deadline-proximity-ramped risk margin;
- group the slots into at most ``N_TIERS`` ascending-price tiers;
- after the solve, attribute scheduled/surplus/deferred energy to calendar
  days as the planned per-day estimate.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, cast

from backend.core.prices import calculate_import_export_prices

if TYPE_CHECKING:
    import pytz

logger = logging.getLogger("darkstar.planner.ev_deferral")

N_TIERS = 24
SLOT_MINUTES = 15
TRAILING_DAYS = 14
TRAILING_MIN_DISTINCT_DAYS = 2

DEFAULT_MARGIN_PERCENT = 12.0
DEFAULT_MARGIN_MAX_PERCENT = 50.0
DEFAULT_RAMP_HOURS = 48.0

# Source reliability order (least reliable last). The per-charger
# ``deferral_price_source`` reports the least reliable source used.
SOURCE_FORECAST = "forecast"
SOURCE_TRAILING = "trailing_average"
SOURCE_HORIZON_MAX = "horizon_max"
_SOURCE_RANK = {SOURCE_FORECAST: 0, SOURCE_TRAILING: 1, SOURCE_HORIZON_MAX: 2}


@dataclass
class DeferralSettings:
    base_percent: float = DEFAULT_MARGIN_PERCENT
    max_percent: float = DEFAULT_MARGIN_MAX_PERCENT
    ramp_hours: float = DEFAULT_RAMP_HOURS


@dataclass
class PostHorizonSlot:
    start: datetime
    hours: float
    known: bool  # published Nordpool price
    price: float  # risk-adjusted deferral price (SEK/kWh)
    source: str


@dataclass
class DeferralTier:
    price: float  # energy-weighted risk-adjusted price (SEK/kWh)
    cap_kwh: float
    slots: list[PostHorizonSlot] = field(default_factory=lambda: [])


@dataclass
class DeferralPlan:
    """Per-charger deferral inputs for Kepler plus the metadata we persist."""

    tiers: list[DeferralTier]
    post_slots: list[PostHorizonSlot]
    source: str | None  # None when there are no post-horizon slots
    effective_margin: float  # fraction, e.g. 0.12


def read_deferral_settings(config: dict[str, Any]) -> DeferralSettings:
    """Read ``ev_planning.*`` risk-margin settings with defaults."""
    raw: Any = config.get("ev_planning")
    section: dict[str, Any] = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}

    def _num(key: str, default: float) -> float:
        value: Any = section.get(key)
        if value is None or isinstance(value, bool):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    base = max(0.0, _num("deferral_risk_margin_percent", DEFAULT_MARGIN_PERCENT))
    max_pct = max(base, _num("deferral_risk_margin_max_percent", DEFAULT_MARGIN_MAX_PERCENT))
    ramp = _num("deferral_risk_ramp_hours", DEFAULT_RAMP_HOURS)
    if ramp <= 0:
        ramp = DEFAULT_RAMP_HOURS
    return DeferralSettings(base_percent=base, max_percent=max_pct, ramp_hours=ramp)


def effective_margin(settings: DeferralSettings, hours_to_deadline: float) -> float:
    """Deadline-proximity-ramped risk margin as a fraction (design D5).

    ``base + (max - base) x clamp(1 - h / ramp_hours, 0, 1)``.
    """
    ramp = min(1.0, max(0.0, 1.0 - hours_to_deadline / settings.ramp_hours))
    pct = settings.base_percent + (settings.max_percent - settings.base_percent) * ramp
    return pct / 100.0


def spot_to_import_price(spot_sek_kwh: float, config: dict[str, Any]) -> float:
    """Convert raw spot (SEK/kWh) to the import price used in-horizon."""
    import_price, _ = calculate_import_export_prices(spot_sek_kwh * 1000.0, config)
    return import_price


def post_horizon_slot_starts(
    horizon_end: datetime, deadline: datetime, slot_minutes: int = SLOT_MINUTES
) -> list[tuple[datetime, float]]:
    """Slots that start at/after ``horizon_end`` and end at or before ``deadline``.

    Returns ``(start, hours)`` pairs on a ``slot_minutes`` grid. A final
    partial slot up to the deadline is included with its fractional length.
    """
    step = timedelta(minutes=slot_minutes)
    out: list[tuple[datetime, float]] = []
    t = horizon_end
    while t < deadline:
        end = min(t + step, deadline)
        hours = (end - t).total_seconds() / 3600.0
        if hours > 0:
            out.append((t, hours))
        t += step
    return out


def fetch_forecast_spot_sync(
    db_path: str, start: datetime, end: datetime, tz: pytz.BaseTzInfo
) -> dict[datetime, float]:
    """Latest-issue ``spot_p50`` per slot start in ``[start, end)``.

    Raises on DB errors so the caller can record the fallback source.
    """
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT slot_start, issue_timestamp, spot_p50
            FROM price_forecasts
            WHERE slot_start >= ? AND slot_start < ?
              AND spot_p50 IS NOT NULL
            """,
            (start.isoformat(), end.isoformat()),
        )
        best: dict[datetime, tuple[str, float]] = {}
        for r in cursor.fetchall():
            try:
                slot_dt = datetime.fromisoformat(r["slot_start"]).astimezone(tz)
            except (TypeError, ValueError):
                continue
            issue = str(r["issue_timestamp"] or "")
            existing = best.get(slot_dt)
            if existing is None or issue > existing[0]:
                best[slot_dt] = (issue, float(r["spot_p50"]))
        return {k: v[1] for k, v in best.items()}
    finally:
        conn.close()


def fetch_trailing_import_avg_sync(
    db_path: str, tz: pytz.BaseTzInfo, now: datetime
) -> float | None:
    """Trailing 14-day average realised import price from ``slot_observations``.

    Requires at least two distinct local calendar days; returns ``None``
    otherwise or on any DB error.
    """
    try:
        conn = sqlite3.connect(db_path, timeout=30)
    except Exception as exc:
        logger.warning("Trailing import price unavailable: cannot open DB: %s", exc)
        return None
    try:
        start = tz.localize(
            datetime.combine(now.astimezone(tz).date() - timedelta(days=TRAILING_DAYS), time.min)
        )
        cursor = conn.execute(
            """
            SELECT slot_start, import_price_sek_kwh
            FROM slot_observations
            WHERE slot_start >= ? AND slot_start < ? AND import_price_sek_kwh IS NOT NULL
            """,
            (start.isoformat(), now.isoformat()),
        )
        values: list[float] = []
        days: set[date] = set()
        for slot_start, price in cursor.fetchall():
            try:
                days.add(datetime.fromisoformat(slot_start).astimezone(tz).date())
            except (TypeError, ValueError):
                continue
            values.append(float(price))
        if len(days) >= TRAILING_MIN_DISTINCT_DAYS and values:
            return sum(values) / len(values)
        return None
    except Exception as exc:
        logger.warning("Trailing import price unavailable: DB query failed: %s", exc)
        return None
    finally:
        conn.close()


def price_post_horizon_slots(
    slot_starts: list[tuple[datetime, float]],
    known_spot: dict[datetime, float],
    forecast_spot: dict[datetime, float],
    config: dict[str, Any],
    margin: float,
    trailing_import: float | None,
    horizon_max_import: float,
) -> tuple[list[PostHorizonSlot], str | None]:
    """Price each post-horizon slot; return the slots and the least-reliable source.

    Published and forecast spot are converted to import prices and marked up
    by ``margin``; the trailing-average import price is marked up too. The
    horizon-max fallback is used as-is (it already means "don't defer").
    """
    out: list[PostHorizonSlot] = []
    worst: str | None = None
    for start, hours in slot_starts:
        known = start in known_spot
        spot = known_spot.get(start)
        if spot is None:
            spot = forecast_spot.get(start)
        if spot is not None:
            price = spot_to_import_price(spot, config) * (1.0 + margin)
            source = SOURCE_FORECAST
        elif trailing_import is not None:
            price = trailing_import * (1.0 + margin)
            source = SOURCE_TRAILING
        else:
            price = horizon_max_import
            source = SOURCE_HORIZON_MAX
        if worst is None or _SOURCE_RANK[source] > _SOURCE_RANK[worst]:
            worst = source
        out.append(
            PostHorizonSlot(start=start, hours=hours, known=known, price=price, source=source)
        )
    return out, worst


def build_tiers(
    slots: list[PostHorizonSlot], max_kw: float, n_tiers: int = N_TIERS
) -> list[DeferralTier]:
    """Group slots ascending by price into at most ``n_tiers`` consecutive-rank blocks.

    Each tier's capacity is ``sum(max_kw x slot_hours)`` and its price the
    energy-weighted mean of its slots' (already risk-adjusted) prices.
    """
    if not slots or max_kw <= 0 or n_tiers <= 0:
        return []
    ordered = sorted(slots, key=lambda s: (s.price, s.start))
    n = len(ordered)
    k = min(n_tiers, n)
    tiers: list[DeferralTier] = []
    for i in range(k):
        lo = (i * n) // k
        hi = ((i + 1) * n) // k
        block = ordered[lo:hi]
        cap = sum(max_kw * s.hours for s in block)
        if cap <= 0:
            continue
        price = sum(s.price * max_kw * s.hours for s in block) / cap
        tiers.append(DeferralTier(price=price, cap_kwh=cap, slots=block))
    return tiers


def build_deferral_plan(
    *,
    horizon_end: datetime,
    deadline: datetime,
    now: datetime,
    max_kw: float,
    config: dict[str, Any],
    settings: DeferralSettings,
    known_spot: dict[datetime, float],
    forecast_spot: dict[datetime, float],
    trailing_import: float | None,
    horizon_max_import: float,
) -> DeferralPlan:
    """Compute the tiers for one charger's goal (empty when deadline is in-horizon)."""
    margin = effective_margin(settings, (deadline - now).total_seconds() / 3600.0)
    starts = post_horizon_slot_starts(horizon_end, deadline)
    if not starts:
        return DeferralPlan(tiers=[], post_slots=[], source=None, effective_margin=margin)
    slots, source = price_post_horizon_slots(
        starts, known_spot, forecast_spot, config, margin, trailing_import, horizon_max_import
    )
    tiers = build_tiers(slots, max_kw)
    return DeferralPlan(tiers=tiers, post_slots=slots, source=source, effective_margin=margin)


def _local_date(dt: datetime, tz: pytz.BaseTzInfo) -> date:
    return dt.astimezone(tz).date()


def planned_by_day(
    *,
    result_slots: list[Any],
    charger_id: str,
    plan: DeferralPlan | None,
    deferred_kwh: list[float] | None,
    deadline: datetime,
    now: datetime,
    tz: pytz.BaseTzInfo,
    first_slot_remaining_h: float | None = None,
) -> list[dict[str, Any]]:
    """Planned per-day estimate ``[{date, kwh, basis}]`` from today through the deadline day.

    - In-horizon: scheduled + planned surplus energy in slots ending by the deadline.
    - Post-horizon: each tier's solved deferred energy attributed to its slots
      cheapest-first, summed per local date.
    - ``basis`` is ``known`` when every slot of that day up to the deadline had
      a published price (all in-horizon slots do), else ``estimated``.
    """
    today = _local_date(now, tz)
    last_day = _local_date(deadline - timedelta(microseconds=1), tz)
    if last_day < today:
        return []

    kwh_by_day: dict[date, float] = {}
    estimated_days: set[date] = set()

    for i, s in enumerate(result_slots):
        if s.end_time > deadline or s.end_time <= now:
            continue
        slot_h = (s.end_time - s.start_time).total_seconds() / 3600.0
        if i == 0 and first_slot_remaining_h is not None:
            slot_h = min(slot_h, first_slot_remaining_h)
        kw = float(s.ev_charger_results.get(charger_id, 0.0) or 0.0)
        kw += float(s.ev_surplus_kw.get(charger_id, 0.0) or 0.0)
        day = _local_date(s.start_time, tz)
        kwh_by_day[day] = kwh_by_day.get(day, 0.0) + kw * slot_h

    if plan is not None:
        for slot in plan.post_slots:
            if not slot.known:
                estimated_days.add(_local_date(slot.start, tz))
        for k, tier in enumerate(plan.tiers):
            remaining = float(deferred_kwh[k]) if deferred_kwh and k < len(deferred_kwh) else 0.0
            if remaining <= 1e-9:
                continue
            max_kw = tier.cap_kwh / sum(s.hours for s in tier.slots) if tier.slots else 0.0
            for slot in sorted(tier.slots, key=lambda s: (s.price, s.start)):
                if remaining <= 1e-9:
                    break
                take = min(remaining, max_kw * slot.hours)
                day = _local_date(slot.start, tz)
                kwh_by_day[day] = kwh_by_day.get(day, 0.0) + take
                remaining -= take

    out: list[dict[str, Any]] = []
    day = today
    while day <= last_day:
        out.append(
            {
                "date": day.isoformat(),
                "kwh": round(kwh_by_day.get(day, 0.0), 3),
                "basis": "estimated" if day in estimated_days else "known",
            }
        )
        day += timedelta(days=1)
    return out
