"""has_water_heater=false must stop every water path, including vacation anti-legionella."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import pytz

from backend.core.water_heating import active_water_heaters, validate_water_heating_config
from planner.pipeline import PlannerPipeline
from planner.solver.adapter import config_to_kepler_config
from planner.solver.kepler import KeplerSolver

HEATER = {"id": "main_tank", "enabled": True, "power_kw": 3, "min_kwh_per_day": 1}


def _config(flag: object) -> dict:
    system = {} if flag is None else {"has_water_heater": flag}
    return {
        "system": system,
        "water_heaters": [HEATER, {"id": "off", "enabled": False}, {"enabled": True}],
    }


def test_helper_respects_flag_default_and_enabled():
    idless = {"enabled": True}
    assert active_water_heaters(_config(False)) == []
    assert active_water_heaters(_config(True)) == [HEATER, idless]
    assert active_water_heaters(_config(None)) == [HEATER, idless]
    assert active_water_heaters({"system": {"has_water_heater": False}}) == []
    assert active_water_heaters({"water_heaters": "bogus"}) == []


def test_validation_skipped_when_flag_off_but_raised_when_on():
    bad = {"id": "t", "max_hours_between_heating": -1}
    off = {"system": {"has_water_heater": False}, "water_heaters": [bad]}
    validate_water_heating_config(off)
    off["water_heating"] = {"defer_up_to_hours": 99}
    validate_water_heating_config(off)
    with pytest.raises(ValueError, match="max_hours_between_heating"):
        validate_water_heating_config({"system": {"has_water_heater": True}, "water_heaters": [bad]})


def test_adapter_returns_no_heaters_when_flag_off():
    cfg = {**_config(False), "config_version": 2, "battery": {"capacity_kwh": 0}}
    assert config_to_kepler_config(cfg).water_heaters == []
    cfg["system"] = {"has_water_heater": True}
    assert [h.id for h in config_to_kepler_config(cfg).water_heaters] == ["main_tank"]


def test_mid_block_detection_gets_no_ids_when_flag_off():
    from planner.pipeline import _detect_mid_block_slots

    import pandas as pd

    prev = [{"start_time": "2026-10-19T15:00:00", "water_heaters": {"main_tank": {"heating_kw": 3}}}]
    now = pd.Timestamp("2026-10-19 15:00", tz="Europe/Stockholm")
    ids = [str(h["id"]) for h in active_water_heaters(_config(False))]
    assert ids == []
    assert not any(_detect_mid_block_slots(prev, ids, now, "Europe/Stockholm", []).values())


@pytest.mark.parametrize("flag", [False, True])
@pytest.mark.asyncio
async def test_vacation_anti_legionella_follows_flag(tmp_path, monkeypatch, flag):
    from tests.fault_injection.test_dst_transitions import make_inputs, planner_config

    monkeypatch.chdir(tmp_path)
    tz = pytz.timezone("Europe/Stockholm")
    now = tz.localize(datetime(2026, 10, 19, 15, 0))
    config = planner_config()
    config.update(
        config_version=2,
        water_heating={"defer_up_to_hours": 6, "vacation_mode": {"enabled": True}},
        water_heaters=[{**HEATER, "sensor": ""}],
        learning={"enable": False, "sqlite_path": str(tmp_path / "x.db")},
    )
    config["system"].update(has_water_heater=flag)
    inputs = make_inputs(now.astimezone(pytz.UTC), hours=8)
    captures = []
    original = KeplerSolver.solve

    def capture(self, solver_input, solver_config):
        captures.append(solver_config)
        return original(self, solver_input, solver_config)

    load = MagicMock(return_value=None)
    save = MagicMock()
    with (
        patch("planner.pipeline.load_last_anti_legionella", load),
        patch("planner.pipeline.save_last_anti_legionella", save),
        patch.object(KeplerSolver, "solve", capture),
    ):
        await PlannerPipeline(config).generate_schedule(
            inputs, mode="baseline", now_override=now, save_to_file=False, publish_state=True
        )
    if flag:
        assert load.called
        assert [h.min_kwh_per_day for h in captures[0].water_heaters] == [9.0]
    else:
        assert not load.called
        assert not save.called
        assert captures[0].water_heaters == []


def test_idless_heater_is_kept_by_helper_and_still_not_planned():
    """Same as HEAD: an id-less heater is not planned, but is not hidden from the recorder."""
    idless = {k: v for k, v in HEATER.items() if k != "id"}
    cfg = {**_config(True), "water_heaters": [idless], "config_version": 2}
    cfg["battery"] = {"capacity_kwh": 0}
    assert active_water_heaters(cfg) == [idless]
    assert config_to_kepler_config(cfg).water_heaters == []
