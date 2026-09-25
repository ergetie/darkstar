"""Deferral pricing inputs for EV goals beyond the known horizon (ev-planning-model §2)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytz

from planner.pipeline import _attach_ev_planned_by_day, _build_ev_deferral_plans
from planner.strategy.ev_deferral import (
    N_TIERS,
    DeferralSettings,
    PostHorizonSlot,
    build_deferral_plan,
    build_tiers,
    effective_margin,
    fetch_forecast_spot_sync,
    fetch_trailing_import_avg_sync,
    planned_by_day,
    post_horizon_slot_starts,
    price_post_horizon_slots,
    read_deferral_settings,
    spot_to_import_price,
)

TZ = pytz.timezone("Europe/Stockholm")
Q = timedelta(minutes=15)
PRICING = {"pricing": {"vat_percent": 25.0, "grid_transfer_fee_sek": 0.25, "energy_tax_sek": 0.44}}


def _local(*args: int) -> datetime:
    return TZ.localize(datetime(*args))


# ---------------------------------------------------------------------------
# 2.5 Deadline-proximity ramp
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("hours", "expected"),
    [(72.0, 0.12), (48.0, 0.12), (24.0, 0.31), (6.0, 0.4525), (0.0, 0.50), (-1.0, 0.50)],
)
def test_effective_margin_ramp_defaults(hours, expected):
    assert effective_margin(DeferralSettings(), hours) == pytest.approx(expected)


def test_ramp_disabled_when_max_equals_base():
    settings = DeferralSettings(base_percent=20.0, max_percent=20.0, ramp_hours=48.0)
    assert effective_margin(settings, 2.0) == pytest.approx(0.20)


def test_settings_defaults_when_absent():
    s = read_deferral_settings({})
    assert (s.base_percent, s.max_percent, s.ramp_hours) == (12.0, 50.0, 48.0)
    s = read_deferral_settings(
        {
            "ev_planning": {
                "deferral_risk_margin_percent": 20,
                "deferral_risk_margin_max_percent": 10,  # below base -> clamped to base
                "deferral_risk_ramp_hours": 24,
            }
        }
    )
    assert (s.base_percent, s.max_percent, s.ramp_hours) == (20.0, 20.0, 24.0)


# ---------------------------------------------------------------------------
# 2.1 Post-horizon classification
# ---------------------------------------------------------------------------
def test_deadline_inside_horizon_has_no_post_horizon_slots():
    horizon_end = _local(2026, 9, 27, 0, 0)  # published through 26th 23:45
    assert post_horizon_slot_starts(horizon_end, _local(2026, 9, 26, 23, 0)) == []


def test_deadline_beyond_horizon_slots_up_to_deadline():
    horizon_end = _local(2026, 9, 26, 0, 0)  # only today published
    starts = post_horizon_slot_starts(horizon_end, _local(2026, 9, 26, 7, 0))
    assert len(starts) == 28
    assert starts[0] == (horizon_end, 0.25)
    assert starts[-1][0] == _local(2026, 9, 26, 6, 45)


def test_partial_last_slot_before_deadline():
    horizon_end = _local(2026, 9, 26, 0, 0)
    starts = post_horizon_slot_starts(horizon_end, _local(2026, 9, 26, 0, 20))
    assert [h for _, h in starts] == [pytest.approx(0.25), pytest.approx(5 / 60)]


# ---------------------------------------------------------------------------
# 2.2 Spot -> import price conversion
# ---------------------------------------------------------------------------
def test_forecast_spot_is_converted_not_compared_raw():
    start = _local(2026, 9, 26, 0, 0)
    slots, source = price_post_horizon_slots(
        [(start, 0.25)], {}, {start: 0.30}, PRICING, 0.0, None, 9.9
    )
    expected = (0.30 + 0.25 + 0.44) * 1.25
    assert source == "forecast"
    assert slots[0].price == pytest.approx(expected)
    assert slots[0].price != pytest.approx(0.30)
    assert spot_to_import_price(0.30, PRICING) == pytest.approx(expected)


def test_published_price_wins_over_forecast_and_marks_known():
    start = _local(2026, 9, 26, 0, 0)
    slots, _ = price_post_horizon_slots(
        [(start, 0.25)], {start: 1.0}, {start: 0.1}, PRICING, 0.0, None, 9.9
    )
    assert slots[0].known is True
    assert slots[0].price == pytest.approx(spot_to_import_price(1.0, PRICING))


# ---------------------------------------------------------------------------
# 2.3 Missing-price fallback
# ---------------------------------------------------------------------------
def test_trailing_average_fallback_applies_margin():
    start = _local(2026, 9, 26, 0, 0)
    slots, source = price_post_horizon_slots([(start, 0.25)], {}, {}, PRICING, 0.12, 1.5, 3.0)
    assert source == "trailing_average"
    assert slots[0].price == pytest.approx(1.5 * 1.12)


def test_horizon_max_fallback_without_history():
    start = _local(2026, 9, 26, 0, 0)
    slots, source = price_post_horizon_slots([(start, 0.25)], {}, {}, PRICING, 0.12, None, 3.0)
    assert source == "horizon_max"
    assert slots[0].price == pytest.approx(3.0)


def test_least_reliable_source_is_reported():
    a, b = _local(2026, 9, 26, 0, 0), _local(2026, 9, 26, 0, 15)
    _, source = price_post_horizon_slots(
        [(a, 0.25), (b, 0.25)], {}, {a: 0.3}, PRICING, 0.0, 1.5, 3.0
    )
    assert source == "trailing_average"


# ---------------------------------------------------------------------------
# 2.4 Tiers
# ---------------------------------------------------------------------------
def _ph(start: datetime, price: float, hours: float = 0.25) -> PostHorizonSlot:
    return PostHorizonSlot(start=start, hours=hours, known=False, price=price, source="forecast")


def test_tiers_are_ascending_capped_and_energy_weighted():
    base = _local(2026, 9, 26, 0, 0)
    slots = [_ph(base + i * Q, float(p)) for i, p in enumerate([3, 1, 2, 4])]
    tiers = build_tiers(slots, max_kw=8.0, n_tiers=2)
    assert len(tiers) == 2
    assert [t.price for t in tiers] == [pytest.approx(1.5), pytest.approx(3.5)]
    assert all(t.cap_kwh == pytest.approx(4.0) for t in tiers)


def test_at_most_n_tiers_and_capacity_preserved():
    base = _local(2026, 9, 26, 0, 0)
    slots = [_ph(base + i * Q, 1.0 + (i % 7) * 0.1) for i in range(4 * 24 * 7)]
    tiers = build_tiers(slots, max_kw=6.9)
    assert len(tiers) == N_TIERS
    assert sum(t.cap_kwh for t in tiers) == pytest.approx(6.9 * 0.25 * len(slots))
    prices = [t.price for t in tiers]
    assert prices == sorted(prices)


def test_margin_applied_to_tier_prices():
    base = _local(2026, 9, 26, 0, 0)
    now = base - timedelta(hours=72)
    deadline = base + timedelta(hours=1)
    forecast = {base + i * Q: 0.30 for i in range(4)}
    plan = build_deferral_plan(
        horizon_end=base,
        deadline=deadline,
        now=now,
        max_kw=6.9,
        config=PRICING,
        settings=DeferralSettings(),
        known_spot={},
        forecast_spot=forecast,
        trailing_import=None,
        horizon_max_import=5.0,
    )
    assert plan.effective_margin == pytest.approx(0.12)
    assert plan.tiers[0].price == pytest.approx(spot_to_import_price(0.30, PRICING) * 1.12)
    assert sum(t.cap_kwh for t in plan.tiers) == pytest.approx(6.9)


def test_no_tiers_when_deadline_in_horizon():
    base = _local(2026, 9, 27, 0, 0)
    plan = build_deferral_plan(
        horizon_end=base,
        deadline=base - timedelta(hours=1),
        now=base - timedelta(hours=20),
        max_kw=6.9,
        config=PRICING,
        settings=DeferralSettings(),
        known_spot={},
        forecast_spot={},
        trailing_import=None,
        horizon_max_import=5.0,
    )
    assert plan.tiers == [] and plan.source is None


# ---------------------------------------------------------------------------
# DB readers
# ---------------------------------------------------------------------------
@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "learning.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE price_forecasts (slot_start TEXT, issue_timestamp TEXT, spot_p50 REAL)")
    conn.execute("CREATE TABLE slot_observations (slot_start TEXT, import_price_sek_kwh REAL)")
    conn.commit()
    conn.close()
    return str(path)


def test_forecast_reader_uses_latest_issue(db_path):
    slot = _local(2026, 9, 27, 1, 0)
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO price_forecasts VALUES (?, ?, ?)",
        [(slot.isoformat(), "2026-09-25T06:00", 0.5), (slot.isoformat(), "2026-09-26T06:00", 0.3)],
    )
    conn.commit()
    conn.close()
    got = fetch_forecast_spot_sync(db_path, slot - Q, slot + Q, TZ)
    assert got == {slot: 0.3}


def test_trailing_average_requires_two_days(db_path):
    now = _local(2026, 9, 26, 12, 0)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO slot_observations VALUES (?, ?)", ((now - timedelta(days=1)).isoformat(), 1.0)
    )
    conn.commit()
    assert fetch_trailing_import_avg_sync(db_path, TZ, now) is None
    conn.execute(
        "INSERT INTO slot_observations VALUES (?, ?)", ((now - timedelta(days=2)).isoformat(), 2.0)
    )
    conn.commit()
    conn.close()
    assert fetch_trailing_import_avg_sync(db_path, TZ, now) == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# Pipeline integration: forecast failure never disables the model (2.3)
# ---------------------------------------------------------------------------
def _input_slots(start: datetime, n: int, price: float = 2.0):
    return [
        SimpleNamespace(start_time=start + i * Q, end_time=start + (i + 1) * Q, import_price_sek_kwh=price)
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_forecast_failure_falls_back_to_trailing_average():
    now = _local(2026, 9, 26, 10, 0)
    slots = _input_slots(now, 56)  # through 24:00
    states = [
        {"id": "ev1", "plugged_in": True, "required_kwh": 20.0, "deadline": now + timedelta(days=4)}
    ]
    cfg = [{"id": "ev1", "type": "current", "max_current_a": 10, "phases": [1, 2, 3]}]
    with (
        patch("backend.core.prices.get_known_spot_by_slot", AsyncMock(return_value={})),
        patch("planner.pipeline.fetch_forecast_spot_sync", side_effect=RuntimeError("db down")),
        patch("planner.pipeline.fetch_trailing_import_avg_sync", return_value=1.2),
    ):
        plans = await _build_ev_deferral_plans(states, cfg, slots, {}, "x.db", TZ, now, 230.0)

    assert states[0]["deferral_price_source"] == "trailing_average"
    assert states[0]["deferral_tiers"]
    # 4-day deadline -> base margin, trailing average marked up
    assert states[0]["effective_margin_percent"] == pytest.approx(12.0)
    assert plans["ev1"].tiers[0].price == pytest.approx(1.2 * 1.12)


@pytest.mark.asyncio
async def test_cold_start_uses_horizon_max():
    now = _local(2026, 9, 26, 10, 0)
    slots = _input_slots(now, 56, price=2.4)
    states = [
        {"id": "ev1", "plugged_in": True, "required_kwh": 20.0, "deadline": now + timedelta(days=4)}
    ]
    cfg = [{"id": "ev1", "rated_power_kw": 3.7}]
    with (
        patch("backend.core.prices.get_known_spot_by_slot", AsyncMock(return_value={})),
        patch("planner.pipeline.fetch_forecast_spot_sync", return_value={}),
        patch("planner.pipeline.fetch_trailing_import_avg_sync", return_value=None),
    ):
        await _build_ev_deferral_plans(states, cfg, slots, {}, "x.db", TZ, now, 230.0)

    assert states[0]["deferral_price_source"] == "horizon_max"
    assert all(p == pytest.approx(2.4) for p, _ in states[0]["deferral_tiers"])


@pytest.mark.asyncio
async def test_deadline_inside_horizon_skips_price_fetch():
    now = _local(2026, 9, 26, 10, 0)
    slots = _input_slots(now, 152)  # through tomorrow 24:00
    states = [
        {"id": "ev1", "plugged_in": True, "required_kwh": 20.0, "deadline": now + timedelta(hours=30)}
    ]
    cfg = [{"id": "ev1", "rated_power_kw": 3.7}]
    known = AsyncMock(return_value={})
    with patch("backend.core.prices.get_known_spot_by_slot", known):
        await _build_ev_deferral_plans(states, cfg, slots, {}, "x.db", TZ, now, 230.0)

    known.assert_not_called()
    assert states[0]["deferral_tiers"] == []
    assert states[0]["deferral_price_source"] is None


# ---------------------------------------------------------------------------
# 4.3 Planned per-day estimate
# ---------------------------------------------------------------------------
def _result_slot(start: datetime, kw: float = 0.0, surplus: float = 0.0):
    return SimpleNamespace(
        start_time=start,
        end_time=start + Q,
        ev_charger_results={"ev1": kw} if kw else {},
        ev_surplus_kw={"ev1": surplus} if surplus else {},
    )


def test_planned_by_day_mixed_known_and_estimated():
    now = _local(2026, 9, 26, 22, 0)
    horizon_end = _local(2026, 9, 27, 0, 0)
    deadline = _local(2026, 9, 29, 7, 0)
    # Today in-horizon: 4 kW scheduled + 2 kW surplus in one slot = 1.5 kWh.
    result_slots = [_result_slot(now, kw=4.0, surplus=2.0)] + [
        _result_slot(now + i * Q) for i in range(1, 8)
    ]
    forecast = {}
    t = horizon_end
    while t < deadline:
        # D+1 cheap, D+2 pricey.
        forecast[t] = 0.1 if t.date() == horizon_end.date() else 1.0
        t += Q
    plan = build_deferral_plan(
        horizon_end=horizon_end,
        deadline=deadline,
        now=now,
        max_kw=4.0,
        config=PRICING,
        settings=DeferralSettings(),
        known_spot={},
        forecast_spot=forecast,
        trailing_import=None,
        horizon_max_import=5.0,
    )
    # Solver deferred 10 kWh, all into the cheapest tier(s).
    deferred = []
    remaining = 10.0
    for tier in plan.tiers:
        take = min(remaining, tier.cap_kwh)
        deferred.append(take)
        remaining -= take

    out = planned_by_day(
        result_slots=result_slots,
        charger_id="ev1",
        plan=plan,
        deferred_kwh=deferred,
        deadline=deadline,
        now=now,
        tz=TZ,
    )
    assert [d["date"] for d in out] == ["2026-09-26", "2026-09-27", "2026-09-28", "2026-09-29"]
    assert out[0] == {"date": "2026-09-26", "kwh": 1.5, "basis": "known"}
    assert out[1]["kwh"] == pytest.approx(10.0)
    assert [d["basis"] for d in out[1:]] == ["estimated"] * 3
    assert out[2]["kwh"] == 0.0 and out[3]["kwh"] == 0.0


def test_planned_by_day_all_known_two_days():
    now = _local(2026, 9, 25, 14, 0)
    deadline = _local(2026, 9, 26, 23, 0)
    result_slots = [_result_slot(_local(2026, 9, 26, 2, 0), kw=8.0)]
    out = planned_by_day(
        result_slots=result_slots,
        charger_id="ev1",
        plan=None,
        deferred_kwh=None,
        deadline=deadline,
        now=now,
        tz=TZ,
    )
    assert out == [
        {"date": "2026-09-25", "kwh": 0.0, "basis": "known"},
        {"date": "2026-09-26", "kwh": 2.0, "basis": "known"},
    ]


def test_attach_planned_by_day_clears_goalless_chargers():
    now = _local(2026, 9, 25, 14, 0)
    states = [{"id": "ev1", "required_kwh": None, "deadline": None, "planned_by_day": ["stale"]}]
    _attach_ev_planned_by_day(SimpleNamespace(slots=[], ev_deferred_kwh={}), states, {}, TZ, now, None)
    assert states[0]["planned_by_day"] == []
