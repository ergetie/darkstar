"""Walk-forward hindsight evaluation on a synthetic archive and database."""

import copy
import gzip
import json
import math
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa

from backend.learning import hindsight_evaluation as he
from backend.learning.models import Base
from tests.learning.battery_synth import (
    CAPACITY_KWH,
    FIRST_DAY,
    TZ,
    flags,
    make_ac_battery_rows,
)

RTE, ELL, ETA = 0.962, 0.07, 0.97
ROOT = math.sqrt(RTE)
TRUE_PAIR = ((1 - ELL) * ROOT, ROOT * ETA)
DAYS = 62
RUN_DAYS = range(42, 52)  # ten runs, each with a full 24 h of data after it


def _run_start(day_offset: int) -> datetime:
    local = TZ.localize(
        datetime.combine(FIRST_DAY + timedelta(days=day_offset), datetime.min.time())
    )
    return (local + timedelta(hours=7, minutes=10)).astimezone(UTC)


def _write_archive(directory: Path, config_pair: tuple[float, float], offsets=RUN_DAYS) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for offset in offsets:
        started = _run_start(offset)
        record = {
            "format_version": 1,
            "run_id": started.strftime("%Y%m%dT%H%M%SZ"),
            "started_at": started.isoformat(),
            "outcome": "ok",
            "config": {
                "timezone": "Europe/Stockholm",
                "system": {
                    "battery": {
                        "capacity_kwh": CAPACITY_KWH,
                        "charge_efficiency": config_pair[0],
                        "discharge_efficiency": config_pair[1],
                    }
                },
            },
            "inputs": {},
        }
        name = f"{started.strftime('%Y%m%dT%H%M%SZ')}-ok.json.gz"
        (directory / name).write_bytes(gzip.compress(json.dumps(record).encode()))


def _write_db(path: Path, rows: list[dict]) -> None:
    engine = sa.create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    columns = [
        "slot_start",
        "slot_end",
        "import_kwh",
        "export_kwh",
        "pv_kwh",
        "load_kwh",
        "water_kwh",
        "ev_charging_kwh",
        "batt_charge_kwh",
        "batt_discharge_kwh",
        "soc_end_percent",
        "quality_flags",
    ]
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                f"INSERT INTO slot_observations ({', '.join(columns)}) "
                f"VALUES ({', '.join(':' + c for c in columns)})"
            ),
            [{c: row[c] for c in columns} for row in rows],
        )
    engine.dispose()


@pytest.fixture(scope="module")
def truth_rows() -> list[dict]:
    return make_ac_battery_rows(DAYS, rte=RTE, charge_loss_ac=ELL, discharge_eff=ETA)


def _load(db: Path) -> list[dict]:
    return he.load_slot_rows(db, _run_start(0) - timedelta(days=60), _run_start(DAYS))


def _evaluate(tmp_path, rows, config_pair, **kwargs):
    archive = tmp_path / "archive"
    _write_archive(archive, config_pair)
    db = tmp_path / "learning.db"
    _write_db(db, rows)
    runs = he.load_archive_runs(archive)
    return he.evaluate_runs(runs, _load(db), **kwargs), runs, db


WRONG_PAIR = (TRUE_PAIR[0] - 0.04, TRUE_PAIR[1] - 0.04)


def test_learned_arm_wins_when_config_is_four_points_off(tmp_path, truth_rows) -> None:
    report, _, _ = _evaluate(tmp_path, truth_rows, WRONG_PAIR)

    gate = report.aggregate[24]
    assert report.evaluable_runs == 10
    assert gate["config_mae_pp"] > 2.0
    assert gate["learned_mae_pp"] < 1.0
    assert gate["learned_mae_pp"] < gate["config_mae_pp"]
    assert report.verdict()[0] is True
    for run in report.runs:
        assert run.learned_pair[0] == pytest.approx(TRUE_PAIR[0], abs=0.01)


def test_config_arm_wins_when_it_is_the_truth_and_the_learned_pair_is_perturbed(
    tmp_path, truth_rows
) -> None:
    report, _, _ = _evaluate(
        tmp_path, truth_rows, TRUE_PAIR, learned_override=WRONG_PAIR, standby_override_w=60.0
    )

    gate = report.aggregate[24]
    assert gate["config_mae_pp"] < 1.0
    assert gate["learned_mae_pp"] > gate["config_mae_pp"] + 0.25
    passed, reason = report.verdict()
    assert not passed and "worse" in reason


def test_ac_pair_applied_to_dc_counters_gives_a_worse_answer(tmp_path, truth_rows) -> None:
    report, runs, db = _evaluate(tmp_path, truth_rows, WRONG_PAIR)
    rows = {r["slot_start"]: r for r in _load(db)}
    run = runs[0]
    result = report.runs[0]
    started = run.started_at
    first = started.replace(minute=0, second=0, microsecond=0)
    ce, de = result.learned_pair
    anchor_key = (first - timedelta(minutes=15)).astimezone(TZ).isoformat()
    soc = rows[anchor_key]["soc_end_percent"] / 100.0 * CAPACITY_KWH
    last = None
    for index in range(96):
        key = (first + timedelta(minutes=15 * index)).astimezone(TZ).isoformat()
        row = rows[key]
        soc += row["batt_charge_kwh"] * ce - row["batt_discharge_kwh"] / de
        last = row["soc_end_percent"]
    dc_error = abs(soc / CAPACITY_KWH * 100.0 - last)

    assert dc_error > result.horizons[24]["learned"].abs_error_pp + 1.0


def test_no_row_after_the_run_start_is_used_for_estimation(tmp_path, truth_rows) -> None:
    baseline, _, _ = _evaluate(tmp_path / "a", truth_rows, WRONG_PAIR)
    corrupted = copy.deepcopy(truth_rows)
    cutoff = (FIRST_DAY + timedelta(days=45)).isoformat()
    for row in corrupted:
        if row["slot_start"] >= cutoff:
            row["batt_discharge_kwh"] = 5.0  # wrecks the RTE of any estimate that sees it
            row["batt_charge_kwh"] = 0.1
    changed, _, _ = _evaluate(tmp_path / "b", corrupted, WRONG_PAIR)

    first_two = {r.run_id: r for r in baseline.runs if r.started_at < _run_start(44).isoformat()}
    assert first_two
    for run in changed.runs:
        if run.run_id in first_two:
            assert run.learned_pair == first_two[run.run_id].learned_pair
    for run in baseline.runs:
        assert datetime.fromisoformat(run.as_of) <= datetime.fromisoformat(run.started_at)


def test_horizon_with_an_ineligible_slot_is_skipped_with_a_reason(tmp_path, truth_rows) -> None:
    rows = copy.deepcopy(truth_rows)
    started = _run_start(RUN_DAYS[0])
    flagged_key = (started.replace(minute=0) + timedelta(hours=10)).astimezone(TZ).isoformat()
    for row in rows:
        if row["slot_start"] == flagged_key:
            row["quality_flags"] = flags(
                {"base_load": {"reliable": False, "reasons": ["negative_after_subtraction"]}}
            )
    report, _, _ = _evaluate(tmp_path, rows, WRONG_PAIR)

    first = next(r for r in report.runs if r.run_id == started.strftime("%Y%m%dT%H%M%SZ"))
    assert 6 in first.horizons
    assert 12 not in first.horizons and 24 not in first.horizons
    assert "not eligible" in first.skipped_horizons[12]
    assert flagged_key in first.skipped_horizons[24]
    assert report.evaluable_runs == 9


def test_too_few_runs_fail_the_verdict_and_say_so(tmp_path, truth_rows) -> None:
    archive = tmp_path / "archive"
    _write_archive(archive, WRONG_PAIR, offsets=range(42, 46))
    db = tmp_path / "learning.db"
    _write_db(db, truth_rows)

    report = he.evaluate_runs(he.load_archive_runs(archive), _load(db))

    assert report.evaluable_runs == 4
    passed, reason = report.verdict()
    assert not passed and "only 4 evaluable runs" in reason


def test_run_without_enough_history_is_skipped_with_the_estimator_reason(
    tmp_path, truth_rows
) -> None:
    archive = tmp_path / "archive"
    _write_archive(archive, WRONG_PAIR, offsets=[5])
    db = tmp_path / "learning.db"
    _write_db(db, truth_rows)

    report = he.evaluate_runs(he.load_archive_runs(archive), _load(db))

    assert report.runs == []
    assert "learned parameters unavailable" in report.skipped_runs[0]["reason"]


def test_report_is_serialisable_and_formattable(tmp_path, truth_rows) -> None:
    report, _, _ = _evaluate(tmp_path, truth_rows, WRONG_PAIR)

    decoded = json.loads(json.dumps(report.to_dict()))
    assert decoded["evaluable_runs"] == 10 and decoded["passed"] is True
    text = he.format_report(report)
    assert "PASS" in text and "24 h" in text


def test_database_is_opened_read_only(tmp_path, truth_rows) -> None:
    db = tmp_path / "learning.db"
    _write_db(db, truth_rows[:100])
    before = db.read_bytes()

    he.load_slot_rows(db, _run_start(0) - timedelta(days=60), _run_start(DAYS))

    assert db.read_bytes() == before
    with pytest.raises(sqlite3.OperationalError):
        connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            connection.execute("DELETE FROM slot_observations")
        finally:
            connection.close()
