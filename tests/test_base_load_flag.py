"""Base-load integrity: flag helpers, the shared unmeasured predicate and its consumers."""

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import pytest
import pytz
from sqlalchemy import create_engine, select

from backend.battery_benchmark import slot_recording
from backend.grid_only_comparison import GridOnlyObservation, build_grid_only_comparison
from backend.learning.models import Base, SlotObservation, unmeasured_device_clause
from backend.measurement_provenance import (
    BASE_LOAD_REASONS,
    base_load_demand_affected,
    base_load_unreliable,
    build_base_load_flag,
)
from backend.observation_provenance import RecordedObservation, calibration_eligible
from ml.load_clean import clean_load_observations, has_unmeasured_device

TZ = pytz.timezone("Europe/Stockholm")


def recording(load_method: str = "derived_history", water_method: str = "power_history") -> dict:
    return {
        "schema_version": 1,
        "semantics": "slot-energy-v1",
        "boundary_fingerprint": "a" * 64,
        "algorithm": "power-history-step-zoh-v1",
        "components": {
            name: {"method": "power_history", "owner": "recorder"}
            for name in (
                "import",
                "export",
                "pv",
                "ev",
                "battery_charge",
                "battery_discharge",
            )
        }
        | {
            "load": {"method": load_method, "owner": "recorder"},
            "water": {"method": water_method, "owner": "recorder"},
        },
        "soc": {"source": "live", "owner": "recorder"},
    }


def flagged(*reasons: str, with_recording: bool = True) -> dict:
    flags: dict[str, Any] = {"source": "recorder"}
    if with_recording:
        flags["recording"] = recording()
    flags["base_load"] = {"reliable": False, "reasons": list(reasons)}
    return flags


class TestHelpers:
    def test_reliable_slot_has_no_flag(self):
        assert build_base_load_flag() is None

    @pytest.mark.parametrize(
        ("kwargs", "reason"),
        [
            ({"clamped": True}, "negative_after_subtraction"),
            ({"partial_devices": True}, "device_partial_coverage"),
            ({"partial_load": True}, "load_partial_coverage"),
            ({"inactive_device_power": True}, "inactive_device_drawing_power"),
        ],
    )
    def test_each_reason(self, kwargs, reason):
        flag = build_base_load_flag(**kwargs)
        assert flag == {"reliable": False, "reasons": [reason]}
        assert reason in BASE_LOAD_REASONS

    def test_reasons_combine_in_a_stable_order(self):
        flag = build_base_load_flag(clamped=True, partial_devices=True)
        assert flag is not None
        assert flag["reasons"] == ["negative_after_subtraction", "device_partial_coverage"]

    @pytest.mark.parametrize(
        ("flags", "unreliable", "demand"),
        [
            ({}, False, False),
            ({"base_load": {"reliable": True}}, False, False),
            ({"base_load": "garbage"}, False, False),
            ({"base_load": {"reliable": False, "reasons": "oops"}}, True, False),
            (flagged("device_partial_coverage"), True, False),
            (flagged("inactive_device_drawing_power"), True, False),
            (flagged("device_disabled_but_configured"), True, False),
            (flagged("negative_after_subtraction"), True, True),
            (flagged("load_partial_coverage"), True, True),
            (flagged("legacy_counter_clamp"), True, True),
            (flagged("legacy_counter_after_clamp"), True, True),
            (flagged("device_partial_coverage", "negative_after_subtraction"), True, True),
        ],
    )
    def test_classification(self, flags, unreliable, demand):
        assert base_load_unreliable(flags) is unreliable
        assert base_load_demand_affected(flags) is demand


@pytest.fixture
def predicate_db(tmp_path):
    path = tmp_path / "pred.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    return str(path)


PREDICATE_CASES: dict[str, str | None] = {
    "reliable": json.dumps({"source": "recorder", "recording": recording()}),
    "null": None,
    "malformed": "{not json",
    "not_object": "[1, 2]",
    "unknown_water": json.dumps({"recording": recording(water_method="unknown")}),
    "unknown_load": json.dumps({"recording": recording(load_method="unknown")}),
    "flag_with_recording": json.dumps(flagged("device_partial_coverage")),
    "flag_without_recording": json.dumps(flagged("legacy_counter_clamp", with_recording=False)),
    "flag_only": json.dumps({"base_load": {"reliable": False, "reasons": []}}),
    "reliable_true": json.dumps({"base_load": {"reliable": True}}),
    "string_false": json.dumps({"base_load": {"reliable": "false"}}),
}


def test_python_and_sql_predicates_agree(predicate_db):
    con = sqlite3.connect(predicate_db)
    for index, raw in enumerate(PREDICATE_CASES.values()):
        con.execute(
            "INSERT INTO slot_observations (slot_start, slot_end, quality_flags, load_kwh) "
            "VALUES (?, ?, ?, 1.0)",
            (f"2026-11-01T00:{index:02d}:00+01:00", f"2026-11-01T01:{index:02d}:00+01:00", raw),
        )
    con.commit()
    con.close()

    engine = create_engine(f"sqlite:///{predicate_db}")
    with engine.connect() as conn:
        sql = {
            row[0]: bool(row[1])
            for row in conn.execute(
                select(SlotObservation.slot_start, unmeasured_device_clause())
            ).all()
        }
    engine.dispose()
    for index, (name, raw) in enumerate(PREDICATE_CASES.items()):
        assert sql[f"2026-11-01T00:{index:02d}:00+01:00"] == has_unmeasured_device(raw), name
    assert has_unmeasured_device(PREDICATE_CASES["flag_without_recording"])
    assert not has_unmeasured_device(PREDICATE_CASES["reliable"])
    assert not has_unmeasured_device(PREDICATE_CASES["string_false"])


def _frame(day: int, flags: list[str | None], load: float = 0.0) -> pd.DataFrame:
    start = TZ.localize(datetime(2026, 11, day))
    index = pd.date_range(start, periods=len(flags), freq="15min", tz=TZ)
    return pd.DataFrame(
        {
            "slot_start": index,
            "load_kwh": load,
            "import_kwh": 0.5,
            "pv_kwh": 0.0,
            "batt_discharge_kwh": 0.0,
            "quality_flags": flags,
        }
    )


class TestCleaning:
    def test_flagged_rows_are_dropped_and_counted(self):
        good = json.dumps({"source": "recorder", "recording": recording()})
        bad = json.dumps(flagged("negative_after_subtraction"))
        legacy = json.dumps(flagged("legacy_counter_clamp", with_recording=False))
        df = _frame(2, [good, bad, legacy, good], load=0.4)
        clean, stats = clean_load_observations(df)
        assert len(clean) == 2
        assert stats["dropped_unmeasured_device_rows"] == 2

    def test_flagged_zero_slots_do_not_feed_the_clamp_day_statistic(self):
        # A recorder-era day with many flagged 0 slots is not a legacy clamp day.
        bad = json.dumps(flagged("negative_after_subtraction", with_recording=False))
        df = _frame(3, [bad] * 96, load=0.0)
        clean, stats = clean_load_observations(df)
        assert stats["dropped_clamp_days"] == 0
        assert stats["dropped_unmeasured_device_rows"] == 96
        assert clean.empty


def _grid_row(start: datetime, flags: dict) -> GridOnlyObservation:
    return GridOnlyObservation(
        start=start,
        import_kwh=1.0,
        export_kwh=0.0,
        import_price_sek_kwh=2.0,
        export_price_sek_kwh=1.0,
        load_kwh=0.0,
        water_kwh=0.5,
        ev_charging_kwh=0.0,
        quality_flags=flags,
    )


def _grid_status(flags: dict) -> str:
    start = datetime(2026, 10, 5, tzinfo=UTC)
    result = build_grid_only_comparison(
        [_grid_row(start, flags)],
        [start],
        timezone=TZ,
        hourly=True,
        axis_start=start,
        axis_end=start + timedelta(minutes=15),
        has_completed_observations=True,
        battery_present=False,
        cycle_cost_kwh=0.0,
    )
    return result["status"]


class TestDemandConsumers:
    @pytest.mark.parametrize("with_recording", [True, False])
    @pytest.mark.parametrize(
        "reason", ["negative_after_subtraction", "load_partial_coverage", "legacy_counter_clamp"]
    )
    def test_grid_only_excludes_demand_affecting_flags(self, reason, with_recording):
        assert _grid_status(flagged(reason, with_recording=with_recording)) == "unavailable"

    @pytest.mark.parametrize("with_recording", [True, False])
    def test_grid_only_keeps_partial_coverage(self, with_recording):
        assert (
            _grid_status(flagged("device_partial_coverage", with_recording=with_recording))
            == "available"
        )

    def test_benchmark_slot_recording(self):
        assert slot_recording({"quality_flags": flagged("device_partial_coverage")}) == "clean"
        assert slot_recording({"quality_flags": flagged("negative_after_subtraction")}) is None
        assert slot_recording({"quality_flags": flagged("load_partial_coverage")}) is None

    def test_calibration_eligibility(self):
        base = RecordedObservation(
            start=datetime(2026, 9, 1, tzinfo=UTC),
            import_kwh=1.0,
            export_kwh=0.0,
            import_price=1.0,
            export_price=0.5,
            pv_kwh=0.0,
            load_kwh=0.5,
            water_kwh=0.0,
            ev_kwh=0.0,
            charge_kwh=0.0,
            discharge_kwh=0.0,
            soc_start_percent=50.0,
            soc_end_percent=50.0,
            quality_flags=flagged("device_partial_coverage"),
        )
        assert calibration_eligible(base)
        assert not calibration_eligible(
            replace(base, quality_flags=flagged("negative_after_subtraction"))
        )
