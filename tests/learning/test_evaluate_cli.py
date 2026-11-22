"""scripts/evaluate_learned_parameters.py: exit codes, replan report and read-only behaviour."""

import gzip
import hashlib
import json
import math
from pathlib import Path

import pytest

from scripts import evaluate_learned_parameters as cli
from tests.learning.battery_synth import CAPACITY_KWH, make_ac_battery_rows
from tests.learning.test_hindsight_evaluation import (
    DAYS,
    ELL,
    ETA,
    RTE,
    RUN_DAYS,
    WRONG_PAIR,
    _run_start,
    _write_archive,
    _write_db,
)
from tests.planner.test_price_reserve_pipeline import make_full_inputs, reserve_config


@pytest.fixture(scope="module")
def truth_rows() -> list[dict]:
    return make_ac_battery_rows(DAYS, rte=RTE, charge_loss_ac=ELL, discharge_eff=ETA)


def _digest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _run(tmp_path: Path, capsys, extra: list[str] | None = None) -> tuple[int, dict]:
    code = cli.main(
        [
            "--archive",
            str(tmp_path / "archive"),
            "--db",
            str(tmp_path / "learning.db"),
            "--json",
            *(extra or []),
        ]
    )
    return code, json.loads(capsys.readouterr().out)


def test_exit_zero_when_learned_is_at_least_as_good(tmp_path, truth_rows, capsys) -> None:
    _write_archive(tmp_path / "archive", WRONG_PAIR)
    _write_db(tmp_path / "learning.db", truth_rows)

    code, report = _run(tmp_path, capsys)

    assert code == 0
    assert report["passed"] is True and report["evaluable_runs"] == 10
    assert report["aggregate"]["24"]["learned_mae_pp"] < report["aggregate"]["24"]["config_mae_pp"]


def test_exit_one_when_learned_is_worse(tmp_path, capsys) -> None:
    # The inverter discharge efficiency is not measurable: the learned pair assumes the 0.97
    # default while this inverter really delivers 0.86, which the run's own config knows.
    lossy_eta = 0.86
    rows = make_ac_battery_rows(DAYS, rte=RTE, charge_loss_ac=ELL, discharge_eff=lossy_eta)
    knowing_config = ((1 - ELL) * math.sqrt(RTE), math.sqrt(RTE) * lossy_eta)
    _write_archive(tmp_path / "archive", knowing_config)
    _write_db(tmp_path / "learning.db", rows)

    code, report = _run(tmp_path, capsys)

    assert code == 1
    assert report["passed"] is False
    assert "worse" in report["reason"]
    gate = report["aggregate"]["24"]
    assert gate["learned_mae_pp"] > gate["config_mae_pp"] + 0.25


def test_exit_one_with_too_few_evaluable_runs(tmp_path, truth_rows, capsys) -> None:
    _write_archive(tmp_path / "archive", WRONG_PAIR, offsets=range(42, 46))
    _write_db(tmp_path / "learning.db", truth_rows)

    code, report = _run(tmp_path, capsys)

    assert code == 1
    assert report["evaluable_runs"] == 4
    assert "only 4 evaluable runs" in report["reason"]


def test_text_report_names_skipped_runs(tmp_path, truth_rows, capsys) -> None:
    _write_archive(tmp_path / "archive", WRONG_PAIR, offsets=[3])
    _write_db(tmp_path / "learning.db", truth_rows)

    code = cli.main(["--archive", str(tmp_path / "archive"), "--db", str(tmp_path / "learning.db")])

    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL" in out and "learned parameters unavailable" in out


def _write_replan_archive(directory: Path, offsets: list[int]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for offset in offsets:
        started = _run_start(offset)
        aligned = started.replace(minute=0, second=0, microsecond=0)
        config = reserve_config(Path("learning.db"), enabled=False)
        config["battery"] = {
            **config["battery"],
            "capacity_kwh": CAPACITY_KWH,
            "charge_efficiency": WRONG_PAIR[0],
            "discharge_efficiency": WRONG_PAIR[1],
        }
        record = {
            "format_version": 1,
            "run_id": started.strftime("%Y%m%dT%H%M%SZ"),
            "started_at": started.isoformat(),
            "outcome": "ok",
            "config": config,
            "inputs": make_full_inputs(aligned),
        }
        name = f"{started.strftime('%Y%m%dT%H%M%SZ')}-ok.json.gz"
        (directory / name).write_bytes(gzip.compress(json.dumps(record, default=str).encode()))


def test_replan_report_lists_both_runs_and_nothing_is_written(
    tmp_path, truth_rows, capsys, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "config.yaml").write_text("system: {}\n")
    monkeypatch.chdir(project)
    monkeypatch.setattr(cli, "REPLAN_WORKDIR", tmp_path / "work")
    _write_replan_archive(tmp_path / "archive", list(RUN_DAYS)[:2])
    _write_db(tmp_path / "learning.db", truth_rows)
    before = {"data": _digest(tmp_path), "project": _digest(project)}

    code, report = _run(tmp_path, capsys, ["--replan"])

    assert code == 1  # only two evaluable runs
    replan = report["replan"]
    assert [item["run_id"] for item in replan] == [r["run_id"] for r in report["runs"]]
    assert len(replan) == 2
    for item in replan:
        assert "error" not in item, item
        assert isinstance(item["differing_action_slots"], int)
        assert isinstance(item["planned_charge_delta_kwh"], float)
    after = {"data": _digest(tmp_path), "project": _digest(project)}
    assert {k: v for k, v in after["data"].items() if not k.startswith("work")} == before["data"]
    assert after["project"] == before["project"]
    assert not (tmp_path / "work" / f"run-{__import__('os').getpid()}").exists()


def test_archive_db_and_config_are_byte_identical_after_a_plain_run(
    tmp_path, truth_rows, capsys, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("learning: {enable: true}\n")
    _write_archive(tmp_path / "archive", WRONG_PAIR)
    _write_db(tmp_path / "learning.db", truth_rows)
    before = _digest(tmp_path)

    _run(tmp_path, capsys)

    assert _digest(tmp_path) == before
