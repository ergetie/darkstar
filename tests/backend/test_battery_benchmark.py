"""Daily battery hindsight benchmark: arithmetic, eligibility and Kepler benchmark mode."""

import json
from datetime import date, datetime, timedelta

import pytest
import pytz

from backend.battery_benchmark import (
    benchmark_day,
    rows_by_local_day,
    schedule_cost,
    summarize,
)
from backend.measurement_provenance import ENERGY_SEMANTICS, PROVENANCE_SCHEMA_VERSION
from planner.solver.kepler import KeplerSolver
from planner.solver.types import KeplerBenchmark, KeplerConfig, KeplerInput, KeplerInputSlot

TZ = pytz.timezone("Europe/Stockholm")
DAY = date(2026, 10, 8)
NOW = TZ.localize(datetime(2026, 10, 11, 0, 10))


def _flags(method: str = "power_history", soc_source: str = "live") -> str:
    component = {"method": method, "owner": "recorder"}
    return json.dumps(
        {
            "recording": {
                "schema_version": PROVENANCE_SCHEMA_VERSION,
                "semantics": ENERGY_SEMANTICS,
                "boundary_fingerprint": "a" * 64,
                "components": {"import": component, "load": dict(component)},
                "soc": {"source": soc_source, "owner": "recorder", "end": {"source": soc_source}},
            }
        }
    )


def _config(**overrides) -> KeplerConfig:
    values = {
        "capacity_kwh": 10.0,
        "min_soc_percent": 0.0,
        "max_soc_percent": 100.0,
        "max_charge_power_kw": 10.0,
        "max_discharge_power_kw": 10.0,
        "charge_efficiency": 1.0,
        "discharge_efficiency": 1.0,
        "wear_cost_sek_per_kwh": 0.0,
        "ramping_cost_sek_per_kw": 0.05,
        "curtailment_penalty_sek": 0.1,
        "timezone_name": "Europe/Stockholm",
    }
    return KeplerConfig(**(values | overrides))


def _day_rows(day: date, row=lambda i, n: {}, soc=lambda i: 50.0) -> list[dict]:
    start = TZ.localize(datetime.combine(day, datetime.min.time())).astimezone(pytz.UTC)
    end = TZ.localize(datetime.combine(day + timedelta(days=1), datetime.min.time()))
    n = int((end.astimezone(pytz.UTC) - start).total_seconds() // 900)
    rows = []
    for i in range(n):
        slot_start = start + timedelta(minutes=15 * i)
        rows.append(
            {
                "slot_start": slot_start.astimezone(TZ).isoformat(),
                "slot_end": (slot_start + timedelta(minutes=15)).astimezone(TZ).isoformat(),
                "import_kwh": 1.0,
                "export_kwh": 0.0,
                "pv_kwh": 0.0,
                "load_kwh": 1.0,
                "water_kwh": 0.0,
                "ev_charging_kwh": 0.0,
                "soc_end_percent": soc(i),
                "import_price_sek_kwh": 1.0 if i < n // 2 else 3.0,
                "export_price_sek_kwh": 0.0,
                "quality_flags": _flags(),
            }
            | row(i, n)
        )
    return rows


def _by_day(rows_for_day: list[dict], day: date = DAY) -> dict:
    return rows_by_local_day(_day_rows(day - timedelta(days=1)) + rows_for_day, TZ)


def _run(rows_for_day: list[dict], day: date = DAY, config: KeplerConfig | None = None):
    return benchmark_day(day, _by_day(rows_for_day, day), config or _config(), NOW)


def test_known_optimum_and_missed_arithmetic():
    # 5 kWh room at start: charge 5 cheap (1 kr), discharge 5 expensive (3 kr) = 10 kr.
    record = _run(_day_rows(DAY))
    assert record["status"] == "scored"
    assert record["no_battery_cost_sek"] == pytest.approx(48 * 1 + 48 * 3)
    assert record["actual_cost_sek"] == pytest.approx(record["no_battery_cost_sek"])
    assert record["ideal_cost_sek"] == pytest.approx(record["no_battery_cost_sek"] - 10.0)
    assert record["missed_sek"] == pytest.approx(10.0)
    assert record["value_ideal_sek"] == pytest.approx(10.0)
    assert record["score"] == pytest.approx(0.0)


def test_score_null_when_hindsight_value_below_one_sek():
    flat = _day_rows(DAY, row=lambda i, n: {"import_price_sek_kwh": 1.0})
    record = _run(flat)
    assert record["status"] == "scored"
    assert record["missed_sek"] == pytest.approx(0.0, abs=1e-6)
    assert record["score"] is None


def test_slots_are_priced_on_net_grid_not_gross_meter_flows():
    rows = [{"load_kwh": 1.0, "water_kwh": 0.0, "ev_charging_kwh": 0.0, "pv_kwh": 0.0,
             "import_price_sek_kwh": 2.0, "export_price_sek_kwh": 1.0}]
    # Gross import 2 / export 1 would bill 3 kr; the net 1 kWh import bills 2 kr.
    assert schedule_cost(rows, [(0.0, 0.0)], 0.0) == pytest.approx(2.0)
    assert schedule_cost(rows, [(0.0, 2.0)], 0.2) == pytest.approx(-1.0 + 0.2)


def test_hindsight_ends_at_the_actual_stored_energy():
    slots = [
        KeplerInputSlot(
            start_time=TZ.localize(datetime(2026, 10, 8, h)),
            end_time=TZ.localize(datetime(2026, 10, 8, h + 1)),
            load_kwh=1.0,
            pv_kwh=0.0,
            import_price_sek_kwh=5.0 - h,
            export_price_sek_kwh=0.0,
        )
        for h in range(4)
    ]
    bench = KeplerBenchmark(terminal_soc_kwh=14.0, no_discharge_slots=[False] * 4)
    result = KeplerSolver().solve(
        KeplerInput(slots, 2.0, benchmark=bench), _config(capacity_kwh=20.0, min_soc_percent=20.0)
    )
    assert result.is_optimal
    assert result.slots[-1].soc_kwh == pytest.approx(14.0)
    # Start below the configured floor stays feasible in benchmark mode.
    assert min(s.soc_kwh for s in result.slots) >= 2.0 - 1e-6
    assert all(s.charge_kwh < 1e-6 or s.discharge_kwh < 1e-6 for s in result.slots)


def test_no_discharge_during_recorded_ev_charging():
    rows = _day_rows(DAY, row=lambda i, n: {"ev_charging_kwh": 1.0, "import_kwh": 2.0} if i >= n // 2 else {})
    record = _run(rows)
    assert record["status"] == "scored"
    # Discharge is blocked in every expensive slot, so hindsight finds nothing to gain.
    assert record["missed_sek"] == pytest.approx(0.0, abs=1e-6)


def test_live_kepler_does_not_use_benchmark_mode():
    assert KeplerInput([], 0.0).benchmark is None


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        (_day_rows(DAY)[:-1], "incomplete_day"),
        (_day_rows(DAY, row=lambda i, n: {"quality_flags": json.dumps({"source": "recorder"})} if i == 5 else {}), "not_clean_recording"),
        (_day_rows(DAY, row=lambda i, n: {"quality_flags": _flags(soc_source="cached")} if i == 5 else {}), "not_clean_recording"),
        (_day_rows(DAY, row=lambda i, n: {"quality_flags": _flags("snapshot")} if i < 3 else {}), "not_clean_recording"),
        (_day_rows(DAY, row=lambda i, n: {"import_price_sek_kwh": None} if i == 7 else {}), "missing_values"),
    ],
)
def test_ineligible_days_are_excluded_with_reason(rows, reason):
    record = _run(rows)
    assert (record["status"], record["reason"]) == ("excluded", reason)
    assert record["score"] is None


def test_end_stock_above_capacity_is_excluded():
    # Full battery whose meter balance keeps charging: modelled end stock > capacity.
    full = lambda i: 100.0  # noqa: E731
    rows = _day_rows(DAY - timedelta(days=1), soc=full) + _day_rows(
        DAY, row=lambda i, n: {"import_kwh": 1.1}, soc=full
    )
    record = benchmark_day(DAY, rows_by_local_day(rows, TZ), _config(), NOW)
    assert (record["status"], record["reason"]) == ("excluded", "stock_out_of_range")


def test_two_snapshot_slots_are_scored_and_counted():
    rows = _day_rows(DAY, row=lambda i, n: {"quality_flags": _flags("snapshot")} if i < 2 else {})
    record = _run(rows)
    assert record["status"] == "scored"
    assert record["snapshot_slots"] == 2


def test_today_and_future_are_never_used():
    today = NOW.date()
    record = benchmark_day(today, _by_day(_day_rows(today), today), _config(), NOW)
    assert record["reason"] == "not_finished"


@pytest.mark.parametrize(("day", "slots"), [(date(2026, 3, 29), 92), (date(2026, 10, 25), 100)])
def test_dst_days_are_scored_over_all_slots(day, slots):
    rows = _day_rows(day)
    assert len(rows) == slots
    later = TZ.localize(datetime(2026, 11, 1))
    record = benchmark_day(day, _by_day(rows, day), _config(), later)
    assert record["status"] == "scored"
    assert record["no_battery_cost_sek"] == pytest.approx((slots // 2) * 1 + (slots - slots // 2) * 3)


def test_capacity_mismatch_excludes_day_with_both_values():
    # 0.5 kWh stored per slot moves SoC 10 pp: implied 5 kWh vs configured 10 kWh.
    rows = _day_rows(
        DAY,
        row=lambda i, n: {"import_kwh": 1.5} if i < 4 else {},
        soc=lambda i: 50.0 + 10.0 * min(i + 1, 4),
    )
    record = _run(rows)
    assert (record["status"], record["reason"]) == ("excluded", "capacity_mismatch")
    assert record["implied_capacity_kwh"] == pytest.approx(5.0)
    assert record["capacity_kwh"] == 10.0


def test_summary_totals_cover_scored_days_only():
    records = [
        {"status": "scored", "reason": None, "missed_sek": 2.0, "value_actual_sek": 8.0, "value_ideal_sek": 10.0},
        {"status": "scored", "reason": None, "missed_sek": 1.0, "value_actual_sek": 4.0, "value_ideal_sek": 5.0},
        {"status": "excluded", "reason": "not_clean_recording", "missed_sek": None},
        {"status": "failed", "reason": "solver_not_optimal", "missed_sek": None},
    ]
    totals = summarize(records)
    assert totals["missed_sek"] == pytest.approx(3.0)
    assert totals["score"] == pytest.approx(12.0 / 15.0)
    assert (totals["days_scored"], totals["days_total"]) == (2, 4)
    assert totals["by_reason"] == {"not_clean_recording": 1, "solver_not_optimal": 1}
    assert summarize([records[2]])["score"] is None
