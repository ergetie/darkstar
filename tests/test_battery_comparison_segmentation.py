from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.battery_comparison import (
    BatteryModel,
    ComparisonBattery,
    GridModel,
    RecordedObservation,
    build_estimated_comparison,
    combine_run_comparisons,
    comparison_row_usable,
    split_comparison_runs,
)

BATTERY = ComparisonBattery(10.0, 10, 95, 2000, 2000)
LEGACY = {"source": "recorder"}


def row(start: datetime, *, soc: float | None = 50.0, pv: float = 1.0, **kw) -> RecordedObservation:
    values = {
        "start": start,
        "import_kwh": 0.0,
        "export_kwh": 0.0,
        "import_price": 2.0,
        "export_price": 1.0,
        "pv_kwh": pv,
        "load_kwh": 0.5,
        "water_kwh": 0.0,
        "ev_kwh": 0.0,
        "charge_kwh": 0.0,
        "discharge_kwh": 0.0,
        "soc_start_percent": 50.0,
        "soc_end_percent": soc,
        "quality_flags": LEGACY,
    }
    values.update(kw)
    return RecordedObservation(**values)


def slots(first: datetime, n: int) -> list[datetime]:
    return [first + timedelta(minutes=15 * i) for i in range(n)]


def usable(item: RecordedObservation) -> bool:
    return comparison_row_usable(item)


def test_runs_break_on_missing_and_unusable_slots() -> None:
    starts = slots(datetime(2026, 9, 1, tzinfo=UTC), 10)
    rows = {s: row(s) for s in starts}
    del rows[starts[3]]
    rows[starts[6]] = row(starts[6], soc=None)  # empty placeholder style row
    rows[starts[7]] = row(starts[7], quality_flags=None)
    runs = split_comparison_runs(starts, rows, usable)
    assert [[r.start for r in run] for run in runs] == [
        starts[0:3],
        starts[4:6],
        starts[8:10],
    ]


def test_all_unusable_yields_no_runs() -> None:
    starts = slots(datetime(2026, 9, 1, tzinfo=UTC), 4)
    rows = {s: row(s, soc=None) for s in starts}
    assert split_comparison_runs(starts, rows, usable) == []


def test_adjacency_uses_elapsed_utc_time_across_the_dst_fold() -> None:
    # 2026-10-25 in Europe/Stockholm: 02:00-03:00 occurs twice (+02:00 then +01:00).
    first = datetime.fromisoformat("2026-10-25T00:00:00+02:00").astimezone(UTC)
    starts = slots(first, 100)
    rows = {s: row(s) for s in starts}
    assert len(split_comparison_runs(starts, rows, usable)) == 1
    # Missing one repeated-hour slot splits the day; wall-clock labels never matter.
    del rows[starts[11]]
    runs = split_comparison_runs(starts, rows, usable)
    assert [len(run) for run in runs] == [11, 88]


def _estimate(rows: list[RecordedObservation], start_soc: float) -> dict:
    result, reason = build_estimated_comparison(
        rows,
        start_soc,
        BATTERY,
        GridModel(1.0, 1.0),
        BatteryModel(0.95, 0.95),
        0.2,
        lambda start: start.replace(minute=0).isoformat(),
        None,
        frozenset(),
    )
    assert reason is None and result is not None
    return result


def test_combined_runs_sum_totals_and_points_are_cumulative_across_runs() -> None:
    starts = slots(datetime(2026, 9, 1, tzinfo=UTC), 24)
    run_a = [row(s, soc=50.0 + 0.1 * i) for i, s in enumerate(starts[:8])]
    run_b = [row(s, soc=40.0) for s in starts[16:]]
    result_a = _estimate(run_a, 50.0)
    result_b = _estimate(run_b, 40.0)
    combined = combine_run_comparisons([(result_a, 8), (result_b, 8)])
    for side in ("darkstar", "self_use"):
        for key, value in combined[side].items():
            assert value == pytest.approx(result_a[side][key] + result_b[side][key], abs=0.002)
    assert combined["saving_sek"] == pytest.approx(
        result_a["saving_sek"] + result_b["saving_sek"], abs=0.002
    )
    points = combined["points"]
    starts_out = [p["start"] for p in points]
    assert starts_out == sorted(set(starts_out))
    # Second run starts from the first run's final cumulative value.
    first_b = next(p for p in points if p["start"] == result_b["points"][0]["start"])
    assert first_b["darkstar_cumulative_comparison_cost_sek"] == pytest.approx(
        result_a["darkstar"]["comparison_cost_sek"]
        + result_b["points"][0]["darkstar_cumulative_comparison_cost_sek"],
        abs=0.002,
    )
    assert points[-1]["darkstar_cumulative_comparison_cost_sek"] == combined["darkstar"][
        "comparison_cost_sek"
    ]
    assert points[-1]["self_use_cumulative_comparison_cost_sek"] == combined["self_use"][
        "comparison_cost_sek"
    ]
    assert combined["through"] == result_b["through"]


def test_single_run_is_returned_unchanged() -> None:
    starts = slots(datetime(2026, 9, 1, tzinfo=UTC), 4)
    result = _estimate([row(s) for s in starts], 50.0)
    assert combine_run_comparisons([(result, 4)]) == result
