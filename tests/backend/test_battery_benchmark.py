"""Daily battery hindsight benchmark: arithmetic, eligibility and Kepler benchmark mode."""

import json
import math
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytz

from backend.battery_benchmark import (
    CAPACITY_TOLERANCE,
    _ev_charging,
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
    rows = [
        {
            "load_kwh": 1.0,
            "water_kwh": 0.0,
            "ev_charging_kwh": 0.0,
            "pv_kwh": 0.0,
            "import_price_sek_kwh": 2.0,
            "export_price_sek_kwh": 1.0,
        }
    ]
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
    rows = _day_rows(
        DAY, row=lambda i, n: {"ev_charging_kwh": 1.0, "import_kwh": 2.0} if i >= n // 2 else {}
    )
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
        (
            _day_rows(DAY, row=lambda i, n: {"quality_flags": json.dumps({"source": "recorder"})}),
            "not_clean_recording",
        ),
        (
            _day_rows(
                DAY,
                row=lambda i, n: {"quality_flags": _flags(soc_source="cached")} if i < 5 else {},
            ),
            "not_clean_recording",
        ),
        (
            _day_rows(DAY, row=lambda i, n: {"quality_flags": _flags("snapshot")} if i < 5 else {}),
            "not_clean_recording",
        ),
        (
            _day_rows(DAY, row=lambda i, n: {"import_price_sek_kwh": None} if i == 7 else {}),
            "missing_values",
        ),
        (
            _day_rows(
                DAY,
                row=lambda i, n: (
                    {"quality_flags": "{}"}
                    if i == 3
                    else {"import_price_sek_kwh": None}
                    if i == 7
                    else {}
                ),
            ),
            "missing_values",
        ),
    ],
)
def test_ineligible_days_are_excluded_with_reason(rows, reason):
    record = _run(rows)
    assert (record["status"], record["reason"]) == ("excluded", reason)
    assert record["score"] is None


def _full_battery_still_charging() -> dict:
    # Full battery whose meter balance keeps charging: modelled end stock > capacity.
    full = lambda i: 100.0  # noqa: E731
    rows = _day_rows(DAY - timedelta(days=1), soc=full) + _day_rows(
        DAY, row=lambda i, n: {"import_kwh": 1.1}, soc=full
    )
    return rows_by_local_day(rows, TZ)


def test_end_stock_above_capacity_is_clamped_with_warning():
    record = benchmark_day(DAY, _full_battery_still_charging(), _config(), NOW)
    assert (record["status"], record["reason"]) == ("scored", None)
    assert "stock_clamped" in record["warnings"]
    # Starts full and ends clamped at full: no stored-energy change remains.
    assert record["stored_change_kwh"] == pytest.approx(0.0)


def test_solver_failure_on_clamped_day_is_stored_as_failed(monkeypatch):
    not_optimal = SimpleNamespace(time_limit_hit=False, status_msg="Infeasible", is_optimal=False)
    monkeypatch.setattr(KeplerSolver, "solve", lambda self, *_: not_optimal)
    record = benchmark_day(DAY, _full_battery_still_charging(), _config(), NOW)
    assert (record["status"], record["reason"]) == ("failed", "solver_not_optimal")
    assert record["solver_status"] == "Infeasible"
    assert "stock_clamped" in record["warnings"]


def test_two_snapshot_slots_are_scored_and_counted():
    rows = _day_rows(DAY, row=lambda i, n: {"quality_flags": _flags("snapshot")} if i < 2 else {})
    record = _run(rows)
    assert record["status"] == "scored"
    assert record["snapshot_slots"] == 2
    assert (record["warnings"], record["unverified_slots"]) == (["unverified_slots"], 2)


def test_one_slot_without_recording_info_is_scored_with_warning():
    # Real data: 95 clean slots and one slot with no recording information.
    rows = _day_rows(DAY, row=lambda i, n: {"quality_flags": None} if i == 40 else {})
    record = _run(rows)
    assert (record["status"], record["reason"]) == ("scored", None)
    assert record["warnings"] == ["unverified_slots"]
    assert (record["unverified_slots"], record["day_slots"]) == (1, 96)


def test_unverified_start_soc_slot_counts_toward_the_limit():
    previous = _day_rows(
        DAY - timedelta(days=1),
        row=lambda i, n: {"quality_flags": _flags(soc_source="cached")} if i == n - 1 else {},
    )
    four_bad = _day_rows(
        DAY, row=lambda i, n: {"quality_flags": _flags("snapshot")} if i < 4 else {}
    )
    record = benchmark_day(DAY, rows_by_local_day(previous + four_bad, TZ), _config(), NOW)
    assert (record["status"], record["reason"]) == ("excluded", "not_clean_recording")
    assert record["unverified_slots"] == 5
    record = benchmark_day(DAY, rows_by_local_day(previous + _day_rows(DAY), TZ), _config(), NOW)
    assert (record["status"], record["unverified_slots"]) == ("scored", 1)


def _gap_slot(i: int, n: int) -> dict:
    # Real data (2026-10-11 15:30): Darkstar recorded nothing for the slot but prices.
    return {
        "quality_flags": None,
        "import_kwh": 0.0,
        "export_kwh": 0.0,
        "pv_kwh": 0.0,
        "load_kwh": 0.0,
        "water_kwh": 0.0,
        "ev_charging_kwh": 0.0,
        "batt_charge_kwh": None,
        "batt_discharge_kwh": None,
        "soc_start_percent": None,
        "soc_end_percent": None,
    }


def test_gap_slot_without_soc_is_scored_with_warning():
    rows = _day_rows(DAY, row=lambda i, n: _gap_slot(i, n) if i == 62 else {})
    record = _run(rows)
    assert (record["status"], record["reason"]) == ("scored", None)
    assert record["warnings"] == ["unverified_slots"]
    assert (record["unverified_slots"], record["day_slots"]) == (1, 96)


def test_gap_slot_missing_energy_counts_as_zero_flow_on_both_sides():
    def row(i: int, n: int) -> dict:
        return {"import_kwh": None, "load_kwh": None} if i == 62 else {}

    gap = _run(_day_rows(DAY, row=row))
    zero = _run(
        _day_rows(DAY, row=lambda i, n: {"import_kwh": 0.0, "load_kwh": 0.0} if i == 62 else {})
    )
    assert (gap["status"], gap["unverified_slots"]) == ("scored", 1)
    assert gap["actual_cost_sek"] == pytest.approx(zero["actual_cost_sek"])
    assert gap["ideal_cost_sek"] == pytest.approx(zero["ideal_cost_sek"])


def test_five_gap_slots_are_excluded():
    rows = _day_rows(DAY, row=lambda i, n: _gap_slot(i, n) if 60 <= i < 65 else {})
    record = _run(rows)
    assert (record["status"], record["reason"]) == ("excluded", "not_clean_recording")
    assert record["unverified_slots"] == 5


def test_gap_slot_plus_three_unverified_slots_is_scored():
    def row(i: int, n: int) -> dict:
        if i == 62:
            return _gap_slot(i, n)
        return {"quality_flags": _flags("snapshot")} if i < 3 else {}

    record = _run(_day_rows(DAY, row=row))
    assert (record["status"], record["unverified_slots"]) == ("scored", 4)
    assert record["warnings"] == ["unverified_slots"]


def test_gap_slot_with_missing_price_is_missing_values():
    rows = _day_rows(
        DAY, row=lambda i, n: _gap_slot(i, n) | {"export_price_sek_kwh": None} if i == 62 else {}
    )
    assert _run(rows)["reason"] == "missing_values"


def test_missing_start_soc_is_missing_values():
    previous = _day_rows(
        DAY - timedelta(days=1), row=lambda i, n: _gap_slot(i, n) if i == n - 1 else {}
    )
    record = benchmark_day(DAY, rows_by_local_day(previous + _day_rows(DAY), TZ), _config(), NOW)
    assert (record["status"], record["reason"]) == ("excluded", "missing_values")


def test_ev_sensor_idle_noise_does_not_block_discharge():
    # Real data: EV sensor idles at ~0.3 W (7.5e-05 kWh/slot). On a net-discharge day the old
    # 1e-6 kWh threshold forbade all discharge and Kepler was infeasible.
    rows = _day_rows(
        DAY,
        row=lambda i, n: {"ev_charging_kwh": 7.5e-05, "import_kwh": 0.9 if i >= n // 2 else 1.0},
    )
    record = _run(rows)
    assert (record["status"], record["reason"]) == ("scored", None)
    assert record["stored_change_kwh"] == pytest.approx(-48 * 0.1 - 96 * 7.5e-05)


def test_ev_threshold_is_average_power_over_the_slot():
    start = TZ.localize(datetime(2026, 10, 8, 12))

    def row(minutes: int, kwh: float) -> dict:
        end = start + timedelta(minutes=minutes)
        return {
            "slot_start": start.isoformat(),
            "slot_end": end.isoformat(),
            "ev_charging_kwh": kwh,
        }

    assert not _ev_charging(row(15, 0.004))  # 16 W
    assert _ev_charging(row(15, 0.006))  # 24 W
    assert not _ev_charging(row(60, 0.016))  # 16 W
    assert _ev_charging(row(60, 0.024))  # 24 W


def test_net_charging_day_records_stored_change_and_null_score():
    # Grid-charges 0.05 kWh/slot all day at a flat price: value shows up the next day.
    rows = _day_rows(DAY, row=lambda i, n: {"import_kwh": 1.05, "import_price_sek_kwh": 1.0})
    record = _run(rows)
    assert record["status"] == "scored"
    assert record["stored_change_kwh"] == pytest.approx(4.8)
    assert record["warnings"] == []
    assert record["value_ideal_sek"] < 0
    assert record["score"] is None


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
    assert record["no_battery_cost_sek"] == pytest.approx(
        (slots // 2) * 1 + (slots - slots // 2) * 3
    )


def test_capacity_mismatch_warns_and_scores():
    # 0.5 kWh stored per slot moves SoC 10 pp: implied 5 kWh vs configured 10 kWh.
    rows = _day_rows(
        DAY,
        row=lambda i, n: {"import_kwh": 1.5} if i < 4 else {},
        soc=lambda i: 50.0 + 10.0 * min(i + 1, 4),
    )
    record = _run(rows)
    assert (record["status"], record["reason"]) == ("scored", None)
    assert record["warnings"] == ["capacity_mismatch"]
    assert record["implied_capacity_kwh"] == pytest.approx(5.0, rel=0.05)
    assert record["capacity_kwh"] == 10.0


def _window_rows(true_capacity_kwh: float, kwh_per_slot: float, step_pp: float = 1.15) -> dict:
    """Eight days (DAY-7 history start day plus its previous day up to DAY) of a battery cycling
    up for one day and down the next at a fixed rate. SoC is reported in coarse steps, with a
    one-slot counter-direction jitter step every 37 slots."""
    first = DAY - timedelta(days=8)
    rows: list[dict] = []
    offset = 0
    for k in range(9):
        day = first + timedelta(days=k)

        def stored(g: int) -> float:
            return kwh_per_slot if (g // 96) % 2 == 0 else -kwh_per_slot

        def true_soc(g: int) -> float:
            stock = sum(stored(j) for j in range(g + 1))
            return 30.0 + stock / true_capacity_kwh * 100.0

        def soc(i: int, base: int = offset) -> float:
            g = base + i
            value = math.floor(true_soc(g) / step_pp) * step_pp
            if g % 37 == 0:
                value += -step_pp if stored(g) > 0 else step_pp
            return value

        day_rows = _day_rows(
            day,
            row=lambda i, n, base=offset: {"import_kwh": 1.0 + stored(base + i)},
            soc=soc,
        )
        offset += len(day_rows)
        rows += day_rows
    return rows_by_local_day(rows, TZ)


def test_large_battery_with_coarse_soc_steps_is_scored_without_warning():
    by_day = _window_rows(true_capacity_kwh=64.0, kwh_per_slot=0.2)
    record = benchmark_day(DAY, by_day, _config(capacity_kwh=64.0), NOW)
    assert (record["status"], record["reason"]) == ("scored", None)
    assert record["implied_capacity_kwh"] == pytest.approx(64.0, rel=CAPACITY_TOLERANCE)
    assert record["warnings"] == []


def test_clearly_wrong_configured_capacity_warns_with_both_values():
    by_day = _window_rows(true_capacity_kwh=40.0, kwh_per_slot=0.2)
    record = benchmark_day(DAY, by_day, _config(capacity_kwh=64.0), NOW)
    assert (record["status"], record["reason"]) == ("scored", None)
    assert record["warnings"] == ["capacity_mismatch"]
    assert record["implied_capacity_kwh"] == pytest.approx(40.0, rel=0.1)
    assert record["capacity_kwh"] == 64.0


def test_small_soc_range_gives_no_capacity_warning():
    # 4.8 kWh swing on a real 40 kWh battery: 12 pp range, below the 20 pp guard.
    by_day = _window_rows(true_capacity_kwh=40.0, kwh_per_slot=0.05)
    record = benchmark_day(DAY, by_day, _config(capacity_kwh=64.0), NOW)
    assert record["status"] == "scored"
    assert record["warnings"] == []


def test_summary_totals_cover_scored_days_only():
    records = [
        {
            "status": "scored",
            "reason": None,
            "missed_sek": 2.0,
            "value_actual_sek": 8.0,
            "value_ideal_sek": 10.0,
        },
        {
            "status": "scored",
            "reason": None,
            "warnings": ["capacity_mismatch"],
            "missed_sek": 1.0,
            "value_actual_sek": 4.0,
            "value_ideal_sek": 5.0,
        },
        {"status": "excluded", "reason": "not_clean_recording", "missed_sek": None},
        {"status": "failed", "reason": "solver_not_optimal", "missed_sek": None},
    ]
    records[0]["stored_change_kwh"] = 1.5
    records[1]["stored_change_kwh"] = -0.5
    records[2]["stored_change_kwh"] = 9.0
    totals = summarize(records)
    assert totals["stored_change_kwh"] == pytest.approx(1.0)
    assert totals["missed_sek"] == pytest.approx(3.0)
    assert totals["score"] == pytest.approx(12.0 / 15.0)
    assert (totals["days_scored"], totals["days_total"]) == (2, 4)
    assert totals["by_reason"] == {"not_clean_recording": 1, "solver_not_optimal": 1}
    assert totals["by_warning"] == {"capacity_mismatch": 1}
    assert summarize([records[2]])["score"] is None
