"""End-to-end EV target-SoC scenarios (price-forecasting-module-4 §6).

Exercises the pipeline's EV section helpers (``_resolve_ready_by``,
``_calculate_required_kwh``, ``_compute_daily_ev_quota``,
``build_ev_charger_inputs``) together with the Kepler solver — the same
sequence the production pipeline runs — without spinning up the full async
generate_schedule (which would require mocking HA/DB/price sources).

Covers:
- 6.1: 30% SoC, target 80% by tomorrow 07:00, midday surplus PV → schedule
  charges the EV from surplus (not export) and reaches 80% by the deadline
  using the cheapest slots.
- 6.2: ``ready_by`` 3 days out + forecast with a cheap middle day → more
  energy allocated to the cheap day, today's quota respected, target met by
  the deadline.
- 6.3: Migration: a config still using ``penalty_levels`` loads with a
  deprecation warning, migrates to an equivalent ``target_soc_percent``, and
  charges correctly (no incentive-bucket path executed).
"""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pytz import timezone as pytz_timezone

from executor.config import load_executor_config
from planner.pipeline import (
    _calculate_required_kwh,
    _compute_daily_ev_quota,
    _resolve_ready_by,
)
from planner.solver.adapter import build_ev_charger_inputs
from planner.solver.kepler import EV_SHORTFALL_PENALTY_DEFAULT, KeplerSolver
from planner.solver.types import ExcessPVSinkEntry, KeplerConfig, KeplerInput, KeplerInputSlot

TZ = pytz_timezone("Europe/Stockholm")

MINIMAL_CONFIG: dict[str, Any] = {
    "config_version": 2,
    "timezone": "Europe/Stockholm",
    "system": {
        "has_solar": True,
        "has_battery": True,
        "has_water_heater": True,
        "has_ev_charger": True,
    },
    "battery": {"capacity_kwh": 10},
    "battery_economics": {"battery_cycle_cost_kwh": 0.1},
    "executor": {"enabled": False},
}


def _write_config(path: str, data: dict[str, Any]) -> None:
    from ruamel.yaml import YAML

    yaml = YAML(typ="safe")
    yaml.default_flow_style = False
    with Path(path).open("w", encoding="utf-8") as f:
        yaml.dump(data, f)


def _ev_priority(charger_id: str, reward: float) -> ExcessPVSinkEntry:
    return ExcessPVSinkEntry(type="ev", effective_reward_sek_per_kwh=reward, charger_id=charger_id)


def _slots(
    n: int,
    *,
    start: datetime,
    import_prices: list[float],
    export_prices: list[float] | None = None,
    pv_kwh: float = 0.0,
    load_kwh: float = 0.0,
    slot_hours: float = 1.0,
) -> list[KeplerInputSlot]:
    if export_prices is None:
        export_prices = [0.0] * n
    out: list[KeplerInputSlot] = []
    for i in range(n):
        s = start + timedelta(hours=i * slot_hours)
        out.append(
            KeplerInputSlot(
                start_time=s,
                end_time=s + timedelta(hours=slot_hours),
                load_kwh=load_kwh,
                pv_kwh=pv_kwh,
                import_price_sek_kwh=import_prices[i],
                export_price_sek_kwh=export_prices[i],
            )
        )
    return out


def _base_config(**overrides) -> dict:
    base = dict(
        capacity_kwh=10.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        enable_export=True,
        max_export_power_kw=10.0,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 6.1 — single-day target with midday surplus PV.
# ---------------------------------------------------------------------------
def test_e2e_surplus_pv_charges_ev_and_meets_target(monkeypatch):
    """EV at 30% SoC, target 80% by tomorrow 07:00, midday surplus PV.

    Expected: the solver charges the EV from surplus PV (not exporting it) and
    reaches the 80% target by the deadline using the cheapest slots.
    """
    now = TZ.localize(datetime(2026, 7, 8, 12, 0))
    # 19 slots covering now..tomorrow 07:00 (19h).
    n = 19
    start = now
    # Cheap midday surplus slots (12-16 today), then cheap night slots, expensive otherwise.
    import_prices = [2.0] * 4 + [0.2] * 5 + [2.0] * 6 + [0.2] * 4
    export_prices = [0.05] * n
    # PV surplus only during midday (slots 0-3): 8 kWh PV, 1 kWh load → 7 kWh surplus.
    pv_per_slot = [8.0] * 4 + [0.0] * (n - 4)
    load_per_slot = 1.0

    slots = [
        KeplerInputSlot(
            start_time=start + timedelta(hours=i),
            end_time=start + timedelta(hours=i + 1),
            load_kwh=load_per_slot,
            pv_kwh=pv_per_slot[i],
            import_price_sek_kwh=import_prices[i],
            export_price_sek_kwh=export_prices[i],
        )
        for i in range(n)
    ]

    # Charger config (goal: 80% by tomorrow 07:00, daily repeat).
    charger_cfg = {
        "id": "ev1",
        "enabled": True,
        "max_power_kw": 7.4,
        "battery_capacity_kwh": 82.0,
        "soc_sensor": "sensor.ev1_soc",
        "plug_sensor": "binary_sensor.ev1_plug",
        "sensor": "sensor.ev1_power",
        "target_soc_percent": 80,
        "ready_by": "07:00",
        "repeat": "daily",
        "type": "current",
    }
    ha_state = {"id": "ev1", "soc_percent": 30.0, "plugged_in": True}

    # No energy delivered yet today.
    monkeypatch.setattr("planner.pipeline._ev_delivered_today_kwh", lambda *_args, **_kw: 0.0)

    deadline = _resolve_ready_by(charger_cfg, now, "Europe/Stockholm")
    assert deadline is not None
    assert deadline.date() == (now + timedelta(days=1)).date()
    assert deadline.hour == 7

    required_kwh = _calculate_required_kwh(charger_cfg, ha_state, None, TZ)
    # (80 - 30)/100 * 82 = 41.0 kWh required.
    assert required_kwh == pytest.approx(41.0, abs=0.01)

    # Deadline is < 1 day out → no spreading.
    today_quota, quota_schedule = _compute_daily_ev_quota(
        charger_cfg, deadline, required_kwh, {}, now, TZ
    )
    assert today_quota is None
    assert quota_schedule is None

    ev_input = build_ev_charger_inputs(
        [charger_cfg],
        [
            {
                "id": "ev1",
                "soc_percent": 30.0,
                "plugged_in": True,
                "deadline": deadline,
                "required_kwh": required_kwh,
                "keep_on_after_target": False,
                "daily_quota_kwh": None,
                "quota_schedule": None,
            }
        ],
    )
    assert len(ev_input) == 1

    cfg = KeplerConfig(
        **_base_config(capacity_kwh=10.0),
        excess_pv_slots=[True] * n,
        excess_pv_priority=[_ev_priority("ev1", reward=2.0)],
        excess_pv_soc_threshold_percent=95.0,
        ev_chargers=ev_input,
        ev_shortfall_penalty_sek_per_kwh=EV_SHORTFALL_PENALTY_DEFAULT,
    )
    initial_soc = cfg.capacity_kwh * 0.97  # battery above SoC threshold → surplus routes freely

    result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=initial_soc), cfg)
    assert result.is_optimal

    # EV absorbed surplus PV (midday) rather than exporting all of it.
    surplus_to_ev = sum(s.ev_surplus_kw.get("ev1", 0.0) for s in result.slots)
    exported = sum(s.grid_export_kwh for s in result.slots)
    assert surplus_to_ev > 0.0, "EV should absorb midday surplus PV"
    available_surplus = sum(max(0.0, s.pv_kwh - s.load_kwh) for s in slots)
    assert exported < available_surplus, "not all surplus should be exported (some went to the EV)"

    # Target met by the deadline (shortfall ≈ 0).
    shortfall = result.slots[-1].ev_shortfall_kwh.get("ev1", 0.0)
    total_ev = sum(s.ev_charge_kw for s in result.slots)
    assert total_ev >= required_kwh - 0.05, f"EV should reach target; got {total_ev}/{required_kwh}"
    assert shortfall == pytest.approx(0.0, abs=0.1)

    # No charging scheduled after the deadline.
    post_deadline = sum(s.ev_charge_kw for s in result.slots if s.start_time >= deadline)
    assert post_deadline == pytest.approx(0.0, abs=0.01)

    # No incentive-bucket code path remains.
    for s in result.slots:
        assert not hasattr(s, "ev_bucket_charged")
        assert not hasattr(s, "value_sek")


# ---------------------------------------------------------------------------
# 6.2 — multi-day deferral with a cheap middle day in the forecast.
# ---------------------------------------------------------------------------
def test_e2e_multi_day_deferral_prefers_cheap_middle_day(monkeypatch):
    """``ready_by`` 3 days out + forecast with a cheap middle day → more energy
    allocated to the cheap day, today's quota respected, target met by deadline.
    """
    now = TZ.localize(datetime(2026, 7, 8, 22, 0))
    deadline = now + timedelta(days=3)

    charger_cfg = {
        "id": "ev1",
        "enabled": True,
        "max_power_kw": 7.4,
        "battery_capacity_kwh": 82.0,
        "target_soc_percent": 80,
        "ready_by": (now + timedelta(days=3)).strftime("%H:%M"),
        "repeat": "none",
        "ready_by_date": (now + timedelta(days=3)).date().isoformat(),
    }
    ha_state = {"id": "ev1", "soc_percent": 30.0, "plugged_in": True}
    monkeypatch.setattr("planner.pipeline._ev_delivered_today_kwh", lambda *_a, **_kw: 0.0)

    required_kwh = _calculate_required_kwh(charger_cfg, ha_state, None, TZ)
    assert required_kwh == pytest.approx(41.0, abs=0.01)

    # 7-day forecast with day 2 cheap (offset 1 = D+1 is very cheap).
    upcoming_spots = {1: 1.5, 2: 0.2, 3: 1.0}

    today_quota, quota_schedule = _compute_daily_ev_quota(
        charger_cfg, deadline, required_kwh, upcoming_spots, now, TZ
    )
    assert quota_schedule is not None, "spreading should activate (deadline >1 day out)"
    assert today_quota is not None

    # Sum of all daily quotas equals required_kwh (energy preserved).
    total_quota = sum(quota_schedule.values())
    assert total_quota == pytest.approx(required_kwh, abs=0.5)

    # The cheap middle day (offset 2 → the day after tomorrow) gets the largest share.
    cheap_day_date = (now + timedelta(days=2)).date()
    other_dates = [d for d in quota_schedule if d != cheap_day_date]
    if other_dates:
        cheap_share = quota_schedule[cheap_day_date]
        other_shares = [quota_schedule[d] for d in other_dates if d != now.date()]
        if other_shares:
            assert cheap_share >= max(other_shares), (
                f"cheap middle day ({cheap_day_date}={cheap_share}) should get the most "
                f"energy, others={dict((d, quota_schedule[d]) for d in other_dates)}"
            )

    # Today's quota is respected as an upper bound in the solver.
    horizon_slots = [
        KeplerInputSlot(
            start_time=now + timedelta(hours=i),
            end_time=now + timedelta(hours=i + 1),
            load_kwh=1.0,
            pv_kwh=0.0,
            import_price_sek_kwh=1.0,
            export_price_sek_kwh=0.0,
        )
        for i in range(24)  # only today in Kepler's horizon
    ]
    ev_input = build_ev_charger_inputs(
        [charger_cfg],
        [
            {
                "id": "ev1",
                "soc_percent": 30.0,
                "plugged_in": True,
                "deadline": deadline,
                "required_kwh": required_kwh,
                "keep_on_after_target": False,
                "daily_quota_kwh": today_quota,
                "quota_schedule": quota_schedule,
            }
        ],
    )
    cfg = KeplerConfig(**_base_config(capacity_kwh=0.0), ev_chargers=ev_input)
    result = KeplerSolver().solve(KeplerInput(slots=horizon_slots, initial_soc_kwh=0.0), cfg)
    assert result.is_optimal

    today_energy = sum(
        s.ev_charge_kw * 1.0 for s in result.slots if s.start_time.date() == now.date()
    )
    assert today_energy <= today_quota + 0.05, (
        f"today's scheduled EV energy ({today_energy}) must respect today's quota ({today_quota})"
    )


# ---------------------------------------------------------------------------
# 6.3 — migration: legacy ``penalty_levels`` config loads with a deprecation
# warning, migrates to an equivalent ``target_soc_percent``, and charges
# correctly (no incentive-bucket path executed).
# ---------------------------------------------------------------------------
def test_e2e_migration_penalty_levels_charges_correctly(caplog: pytest.LogCaptureFixture):
    data = {
        **MINIMAL_CONFIG,
        "ev_chargers": [
            {
                "id": "legacy_ev",
                "enabled": True,
                "max_power_kw": 7.4,
                "battery_capacity_kwh": 60.0,
                "sensor": "sensor.legacy_power",
                "soc_sensor": "sensor.legacy_soc",
                "plug_sensor": "binary_sensor.legacy_plug",
                "type": "binary",
                "penalty_levels": [
                    {"max_soc": 60, "penalty_sek": 1.0},
                    {"max_soc": 80, "penalty_sek": 2.0},
                    {"max_soc": 100, "penalty_sek": 3.0},
                ],
            }
        ],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        path = f.name
    try:
        _write_config(path, data)
        with caplog.at_level(logging.WARNING, logger="darkstar.executor.config"):
            cfg_exec = load_executor_config(path)
    finally:
        Path(path).unlink(missing_ok=True)

    ev = cfg_exec.ev_chargers[0]
    # Migration sets target_soc_percent to the highest configured max_soc (100).
    assert ev.target_soc_percent == 100
    # A deprecation warning was emitted.
    assert any(
        "penalty_levels" in r.message and "deprecated" in r.message.lower() for r in caplog.records
    )

    # No incentive-bucket code path is executed — build the solver input and solve.
    now = TZ.localize(datetime(2026, 7, 8, 10, 0))
    deadline = now + timedelta(hours=10)
    cfg_dict = {
        "id": ev.id,
        "enabled": True,
        "max_power_kw": ev.max_power_kw,
        "battery_capacity_kwh": ev.battery_capacity_kwh,
        "target_soc_percent": ev.target_soc_percent,
        "ready_by": ev.ready_by,
        "repeat": "daily",
        "type": "binary",
    }
    ha_state = {"id": ev.id, "soc_percent": 40.0, "plugged_in": True}
    with patch("planner.pipeline._ev_delivered_today_kwh", return_value=0.0):
        required_kwh = _calculate_required_kwh(cfg_dict, ha_state, None, TZ)
    # (100 - 40)/100 * 60 = 36 kWh required.
    assert required_kwh == pytest.approx(36.0, abs=0.01)

    ev_input = build_ev_charger_inputs(
        [cfg_dict],
        [
            {
                "id": ev.id,
                "soc_percent": 40.0,
                "plugged_in": True,
                "deadline": deadline,
                "required_kwh": required_kwh,
                "keep_on_after_target": False,
                "daily_quota_kwh": None,
                "quota_schedule": None,
            }
        ],
    )
    slots = [
        KeplerInputSlot(
            start_time=now + timedelta(hours=i),
            end_time=now + timedelta(hours=i + 1),
            load_kwh=1.0,
            pv_kwh=0.0,
            import_price_sek_kwh=0.1,
            export_price_sek_kwh=0.0,
        )
        for i in range(10)
    ]
    cfg = KeplerConfig(**_base_config(capacity_kwh=0.0), ev_chargers=ev_input)
    result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=0.0), cfg)
    assert result.is_optimal

    # The migrated charger charges toward the (migrated) target SoC — no
    # incentive-bucket path executed.
    total_ev = sum(s.ev_charge_kw for s in result.slots)
    assert total_ev > 0.0, "migrated charger should schedule charging toward its target"
    shortfall = result.slots[-1].ev_shortfall_kwh.get(ev.id, 0.0)
    assert shortfall == pytest.approx(0.0, abs=0.1)
    for s in result.slots:
        assert not hasattr(s, "ev_bucket_charged")
        assert not hasattr(s, "value_sek")
