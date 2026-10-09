from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
import pytz

from backend.core.ha_client import get_initial_state
from backend.core.water_progress import read_water_heating_progress
from backend.learning.models import Base
from backend.learning.store import LearningStore
from backend.measurement_provenance import recording_metadata
from planner.solver.adapter import build_water_heater_inputs
from planner.solver.kepler import KeplerSolver
from planner.solver.types import KeplerConfig, KeplerInput, KeplerInputSlot


@pytest.mark.parametrize("control_type", ["switch", "temperature"])
@pytest.mark.asyncio
async def test_store_initial_state_adapter_solver_credits_progress_once(tmp_path, control_type):
    tz = pytz.timezone("Europe/Stockholm")
    bucket_start = tz.localize(datetime(2026, 1, 15, 6, 0))
    row_end = bucket_start + timedelta(minutes=15)
    cutoff = bucket_start + timedelta(minutes=30)
    db_path = tmp_path / "planner_learning.db"
    config = {
        "timezone": "Europe/Stockholm",
        "learning": {"sqlite_path": str(db_path)},
        "system": {"battery": {"capacity_kwh": 10}, "has_water_heater": True},
        "input_sensors": {},
        "water_heating": {"defer_up_to_hours": 6, "enable_top_ups": True},
        "water_heaters": [
            {
                "id": "tank",
                "enabled": True,
                "power_kw": 3.0,
                "min_kwh_per_day": 6.0,
                "max_hours_between_heating": 8,
                "sensor": "sensor.tank_power",
                "control_type": control_type,
                "idle_power_threshold_kw": 0.1,
            }
        ],
        "ev_chargers": [],
    }
    store = LearningStore(str(db_path), tz)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    flags = {
        "source": "recorder",
        "recording": recording_metadata(
            config, {"water": {"method": "power_history", "owner": "recorder"}}, "unavailable"
        ),
        "water_heater_energy": {
            "schema_version": 1,
            "semantics": "active-water-energy-v1",
            "devices": {
                "tank": {
                    "energy_kwh": 0.75,
                    "source": "power_history",
                    "idle_power_threshold_kw": 0.1,
                    "coverage": "complete",
                }
            },
        },
    }
    await store.store_slot_observations(
        pd.DataFrame(
            [
                {
                    "slot_start": bucket_start,
                    "slot_end": row_end,
                    "water_kwh": 0.75,
                    "quality_flags": flags,
                }
            ]
        )
    )
    await store.close()
    history = [
        {
            "entity_id": "sensor.tank_power",
            "state": "3.0",
            "last_changed": bucket_start.isoformat(),
            "attributes": {"unit_of_measurement": "kW"},
        },
        {
            "entity_id": "sensor.tank_power",
            "state": "3.0",
            "last_changed": row_end.isoformat(),
            "attributes": {"unit_of_measurement": "kW"},
        },
    ]
    with (
        patch("backend.core.ha_client.secrets.load_yaml", return_value=config),
        patch("backend.core.ha_client.secrets.load_home_assistant_config", return_value={}),
        patch(
            "backend.core.ha_client.get_ha_sensor_kw_normalized",
            new=AsyncMock(return_value=0.06),
        ),
        patch(
            "backend.core.water_progress.get_power_history_batch",
            new=AsyncMock(return_value={"sensor.tank_power": history}),
        ) as history_reader,
    ):
        initial_state = await get_initial_state("unused.yaml", progress_cutoff=cutoff)
        repeated = await read_water_heating_progress(config, cutoff, str(db_path))
        later = await read_water_heating_progress(
            config, cutoff + timedelta(minutes=15), str(db_path)
        )
        default_cutoff_config = {
            **config,
            "water_heaters": [{**config["water_heaters"][0], "idle_power_threshold_kw": 0.0}],
        }
        zero_power = await read_water_heating_progress(
            default_cutoff_config,
            cutoff,
            str(db_path),
            current_power_kw={"tank": 0.0},
        )

    state = initial_state["water_heater_states"][0]
    assert state["heated_today_kwh"] == pytest.approx(1.5)
    assert state["progress_coverage"] == "complete"
    assert state["active_heating"] is False
    assert history_reader.await_args.args[0] == ["sensor.tank_power"]
    # The stored 06:00-06:15 bucket and overlapping HA samples count once.
    assert repeated[0]["heated_today_kwh"] == pytest.approx(1.5)
    assert later[0]["heated_today_kwh"] == pytest.approx(2.25)
    assert zero_power[0]["active_heating"] is False

    water_inputs = build_water_heater_inputs(
        config["water_heaters"], config["water_heating"], initial_state["water_heater_states"]
    )
    assert water_inputs[0].heated_today_kwh == pytest.approx(1.5)
    solver_config = KeplerConfig(
        capacity_kwh=0,
        min_soc_percent=0,
        max_soc_percent=100,
        max_charge_power_kw=5,
        max_discharge_power_kw=5,
        charge_efficiency=1,
        discharge_efficiency=1,
        wear_cost_sek_per_kwh=0,
        water_heaters=water_inputs,
        water_reliability_penalty_sek=100,
        defer_up_to_hours=6,
        timezone_name="Europe/Stockholm",
    )
    slots = [
        KeplerInputSlot(
            start_time=cutoff + timedelta(minutes=15 * index),
            end_time=cutoff + timedelta(minutes=15 * (index + 1)),
            load_kwh=0,
            pv_kwh=0,
            import_price_sek_kwh=1,
            export_price_sek_kwh=0,
        )
        for index in range(16)
    ]
    result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=0), solver_config)
    planned_kwh = sum(slot.water_heater_results.get("tank", 0) * 0.25 for slot in result.slots)
    assert planned_kwh == pytest.approx(4.5)

    # The former production path supplied zero progress and kept the full quota outstanding.
    baseline_inputs = build_water_heater_inputs(
        config["water_heaters"], config["water_heating"], []
    )
    baseline_config = replace(solver_config, water_heaters=baseline_inputs)
    baseline = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=0), baseline_config)
    baseline_kwh = sum(slot.water_heater_results.get("tank", 0) * 0.25 for slot in baseline.slots)
    assert baseline_kwh == pytest.approx(6.0)


@pytest.mark.asyncio
async def test_legacy_aggregate_requires_single_matching_heater_ownership(tmp_path):
    tz = pytz.timezone("Europe/Stockholm")
    slot_start = tz.localize(datetime(2026, 1, 15, 6, 0))
    slot_end = slot_start + timedelta(minutes=15)
    cutoff = slot_end
    db_path = tmp_path / "legacy.db"
    config = {
        "timezone": "Europe/Stockholm",
        "learning": {"sqlite_path": str(db_path)},
        "system": {"has_water_heater": True},
        "water_heating": {"defer_up_to_hours": 6},
        "water_heaters": [
            {"id": "tank", "enabled": True, "sensor": "sensor.tank", "idle_power_threshold_kw": 0.0}
        ],
    }
    store = LearningStore(str(db_path), tz)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    flags = {
        "source": "recorder",
        "recording": recording_metadata(
            config, {"water": {"method": "power_history", "owner": "recorder"}}, "unavailable"
        ),
    }
    await store.store_slot_observations(
        pd.DataFrame(
            [
                {
                    "slot_start": slot_start,
                    "slot_end": slot_end,
                    "water_kwh": 0.75,
                    "quality_flags": flags,
                }
            ]
        )
    )
    multi_config = {
        **config,
        "water_heaters": [
            {
                "id": "tank",
                "enabled": True,
                "sensor": "sensor.tank",
                "idle_power_threshold_kw": 0.0,
            },
            {
                "id": "upstairs",
                "enabled": True,
                "sensor": "sensor.upstairs",
                "idle_power_threshold_kw": 0.0,
            },
        ],
    }
    await store.store_slot_observations(
        pd.DataFrame(
            [
                {
                    "slot_start": slot_end,
                    "slot_end": slot_end + timedelta(minutes=15),
                    "water_kwh": 0.75,
                    "quality_flags": {
                        "source": "recorder",
                        "recording": recording_metadata(
                            multi_config,
                            {"water": {"method": "power_history", "owner": "recorder"}},
                            "unavailable",
                        ),
                        "water_heater_energy": {
                            "schema_version": 1,
                            "semantics": "active-water-energy-v1",
                            "devices": {
                                "tank": {
                                    "energy_kwh": 0.25,
                                    "source": "power_history",
                                    "idle_power_threshold_kw": 0.0,
                                    "coverage": "complete",
                                },
                                "upstairs": {
                                    "energy_kwh": 0.5,
                                    "source": "power_history",
                                    "idle_power_threshold_kw": 0.0,
                                    "coverage": "complete",
                                },
                            },
                        },
                    },
                }
            ]
        )
    )
    await store.close()

    with patch(
        "backend.core.water_progress.get_power_history_batch", new=AsyncMock(return_value=None)
    ):
        single = await read_water_heating_progress(config, cutoff, str(db_path))
        changed_config = {
            **config,
            "water_heaters": [{**config["water_heaters"][0], "sensor": "sensor.replaced"}],
        }
        changed = await read_water_heating_progress(changed_config, cutoff, str(db_path))
        after_rollover = await read_water_heating_progress(
            config, cutoff + timedelta(days=1), str(db_path)
        )
        ambiguous_config = {
            **config,
            "water_heaters": [
                config["water_heaters"][0],
                {"id": "upstairs", "enabled": True, "sensor": "sensor.upstairs"},
            ],
        }
        ambiguous = await read_water_heating_progress(ambiguous_config, cutoff, str(db_path))
        per_device = await read_water_heating_progress(
            multi_config,
            cutoff + timedelta(minutes=15),
            str(db_path),
        )

    assert single[0]["heated_today_kwh"] == pytest.approx(0.75)
    assert single[0]["progress_source"] == "legacy"
    assert changed[0]["heated_today_kwh"] == 0.0
    assert changed[0]["progress_coverage"] == "unavailable"
    assert after_rollover[0]["heated_today_kwh"] == 0.0
    assert {state["heated_today_kwh"] for state in ambiguous} == {0.0}
    assert all(state["progress_coverage"] == "unavailable" for state in ambiguous)
    assert {state["id"]: state["heated_today_kwh"] for state in per_device} == {
        "tank": pytest.approx(0.25),
        "upstairs": pytest.approx(0.5),
    }


@pytest.mark.parametrize("control_type", ["switch", "temperature"])
@pytest.mark.parametrize("advance_minutes", [0, 15])
@pytest.mark.asyncio
async def test_whole_day_forecasts_and_real_pipeline_use_first_solver_slot(
    tmp_path, monkeypatch, control_type, advance_minutes
):
    import yaml

    from backend.core.forecasts import get_all_input_data
    from planner.pipeline import PlannerPipeline
    from tests.fault_injection.test_dst_transitions import planner_config

    monkeypatch.chdir(tmp_path)
    tz = pytz.timezone("Europe/Stockholm")
    cutoff = (datetime.now(tz) + timedelta(days=2)).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    midnight = cutoff.replace(hour=0)
    db_path = tmp_path / "progress.db"
    config = planner_config()
    config.update(
        config_version=2,
        learning={"enable": False, "sqlite_path": str(db_path)},
        water_heating={"defer_up_to_hours": 6, "enable_top_ups": False},
        water_heaters=[
            {
                "id": "tank",
                "enabled": True,
                "power_kw": 3,
                "min_kwh_per_day": 6,
                "max_hours_between_heating": 8,
                "sensor": "sensor.tank",
                "control_type": control_type,
                "idle_power_threshold_kw": 0.1,
            }
        ],
    )
    config["system"].update(has_water_heater=True, has_battery=False, has_solar=False)
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config))
    store = LearningStore(str(db_path), tz)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    flags = {
        "source": "recorder",
        "recording": recording_metadata(
            config, {"water": {"method": "power_history", "owner": "recorder"}}, "unavailable"
        ),
        "water_heater_energy": {
            "schema_version": 1,
            "semantics": "active-water-energy-v1",
            "devices": {
                "tank": {
                    "energy_kwh": 0.75,
                    "source": "power_history",
                    "idle_power_threshold_kw": 0.1,
                    "coverage": "complete",
                }
            },
        },
    }
    await store.store_slot_observations(
        pd.DataFrame(
            [
                {
                    "slot_start": cutoff - timedelta(minutes=15),
                    "slot_end": cutoff,
                    "water_kwh": 0.75,
                    "quality_flags": flags,
                }
            ]
        )
    )
    await store.close()
    prices = [
        {
            "start_time": midnight + timedelta(minutes=15 * i),
            "end_time": midnight + timedelta(minutes=15 * (i + 1)),
            "import_price_sek_kwh": 1,
            "export_price_sek_kwh": 0,
        }
        for i in range(96)
    ]
    forecasts = [
        {"start_time": slot["start_time"], "pv_forecast_kwh": 0, "load_forecast_kwh": 0}
        for slot in prices
    ]
    history = [
        {
            "state": "0",
            "last_changed": (midnight + timedelta(hours=6)).isoformat(),
            "attributes": {"unit_of_measurement": "kW"},
        },
        {"state": "3", "last_changed": cutoff.isoformat(), "attributes": {}},
    ]
    captures = []
    original_solve = KeplerSolver.solve

    def capture(self, solver_input, solver_config):
        captures.append((solver_input, solver_config))
        return original_solve(self, solver_input, solver_config)

    with (
        patch("backend.core.forecasts.datetime") as clock,
        patch("backend.core.ha_client.datetime") as initial_clock,
        patch("backend.core.prices.get_nordpool_data", new=AsyncMock(return_value=prices)),
        patch(
            "backend.core.forecasts.get_forecast_data",
            new=AsyncMock(return_value={"slots": forecasts}),
        ),
        patch(
            "backend.core.ha_client.get_ha_sensor_kw_normalized", new=AsyncMock(return_value=0.06)
        ),
        patch(
            "backend.core.water_progress.get_power_history_batch",
            new=AsyncMock(return_value={"sensor.tank": history}),
        ),
        patch.object(KeplerSolver, "solve", capture),
    ):
        clock.now.return_value = cutoff + timedelta(minutes=7)
        initial_clock.now.return_value = cutoff + timedelta(minutes=7)
        initial_clock.fromisoformat.side_effect = datetime.fromisoformat
        inputs = await get_all_input_data(str(config_path))
        assert inputs["initial_state"]["water_progress_cutoff"] == cutoff
        assert inputs["initial_state"]["water_heater_states"][0][
            "heated_today_kwh"
        ] == pytest.approx(0.75)
        await PlannerPipeline(config).generate_schedule(
            inputs,
            mode="baseline",
            now_override=cutoff + timedelta(minutes=advance_minutes),
            save_to_file=False,
            publish_state=False,
        )

    solver_input, solver_config = captures[0]
    assert solver_input.slots[0].start_time == cutoff + timedelta(minutes=advance_minutes)
    assert solver_config.water_heaters[0].heated_today_kwh == pytest.approx(
        0.75 + advance_minutes * 3 / 60
    )
    assert solver_config.water_heaters[0].progress_coverage == "complete"


@pytest.mark.asyncio
async def test_repeated_dst_hour_keeps_attributable_store_energy(tmp_path):
    tz = pytz.timezone("Europe/Stockholm")
    # The second 02:15 is AFTER the first 02:30 quota boundary.
    start = tz.localize(datetime(2026, 10, 25, 2, 15), is_dst=False)
    end = start + timedelta(minutes=15)
    config = {
        "timezone": "Europe/Stockholm",
        "water_heating": {"defer_up_to_hours": 2.5},
        "water_heaters": [{"id": "tank", "sensor": "sensor.tank"}],
    }
    db_path = tmp_path / "dst.db"
    store = LearningStore(str(db_path), tz)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    flags = {
        "water_heater_energy": {
            "schema_version": 1,
            "semantics": "active-water-energy-v1",
            "devices": {
                "tank": {
                    "energy_kwh": 0.75,
                    "source": "power_history",
                    "coverage": "complete",
                    "idle_power_threshold_kw": 0,
                }
            },
        }
    }
    await store.store_slot_observations(
        pd.DataFrame(
            [{"slot_start": start, "slot_end": end, "water_kwh": 0.75, "quality_flags": flags}]
        )
    )
    await store.close()
    with patch(
        "backend.core.water_progress.get_power_history_batch", new=AsyncMock(return_value=None)
    ):
        result = await read_water_heating_progress(config, end, str(db_path))
    assert result[0]["heated_today_kwh"] == pytest.approx(0.75)
    assert result[0]["progress_coverage"] == "partial"


def test_recent_history_outage_retains_only_known_intervals():
    from backend.core.water_progress import _history_energy

    tz = pytz.timezone("Europe/Stockholm")
    start = tz.localize(datetime(2026, 1, 15, 6))
    states = [
        {
            "state": "3000",
            "last_changed": start.isoformat(),
            "attributes": {"unit_of_measurement": "W"},
        },
        {"state": "unavailable", "last_changed": (start + timedelta(minutes=5)).isoformat()},
        {"state": "60", "last_changed": (start + timedelta(minutes=10)).isoformat()},
    ]
    energy, covered_seconds = _history_energy(states, start, start + timedelta(minutes=15), 0.1, tz)
    assert energy == pytest.approx(0.25)
    assert covered_seconds == 600


@pytest.mark.parametrize("control_type", ["switch", "temperature"])
@pytest.mark.asyncio
async def test_no_power_sensor_keeps_unknown_progress_and_controllable_heater(
    tmp_path, control_type
):
    tz = pytz.timezone("Europe/Stockholm")
    config = {
        "timezone": "Europe/Stockholm",
        "water_heating": {"defer_up_to_hours": 6},
        "water_heaters": [
            {"id": "tank", "power_kw": 3, "min_kwh_per_day": 4, "control_type": control_type}
        ],
    }
    store = AsyncMock()
    store.get_water_heater_energy_range.return_value = []
    with (
        patch("backend.core.water_progress.LearningStore", return_value=store),
        patch("backend.core.water_progress.get_power_history_batch", new=AsyncMock()) as history,
    ):
        states = await read_water_heating_progress(
            config, tz.localize(datetime(2026, 1, 15, 12)), str(tmp_path / "unused.db")
        )
    assert states[0]["heated_today_kwh"] == 0
    assert states[0]["progress_coverage"] == "unavailable"
    assert states[0]["active_heating"] is None
    history.assert_not_awaited()
    inputs = build_water_heater_inputs(config["water_heaters"], config["water_heating"], states)
    assert len(inputs) == 1
    assert inputs[0].min_kwh_per_day == 4


@pytest.mark.parametrize("resolution_minutes", [30, 60])
@pytest.mark.asyncio
async def test_future_coarse_solver_slot_never_credits_future_power(tmp_path, resolution_minutes):
    import yaml

    from backend.core.forecasts import get_all_input_data
    from tests.fault_injection.test_dst_transitions import planner_config

    tz = pytz.timezone("Europe/Stockholm")
    measured_at = tz.localize(datetime(2026, 10, 20, 12, 17))
    midnight = measured_at.replace(hour=0, minute=0)
    config = planner_config()
    config.update(
        config_version=2,
        water_heating={"defer_up_to_hours": 6},
        water_heaters=[{"id": "tank", "sensor": "sensor.tank", "power_kw": 3}],
    )
    config["system"].update(has_water_heater=True, has_battery=False)
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config))
    prices = [
        {
            "start_time": midnight + timedelta(minutes=resolution_minutes * i),
            "end_time": midnight + timedelta(minutes=resolution_minutes * (i + 1)),
            "import_price_sek_kwh": 1,
            "export_price_sek_kwh": 0,
        }
        for i in range(1440 // resolution_minutes)
    ]
    store = AsyncMock()
    store.get_water_heater_energy_range.return_value = []
    history = [
        {"state": "0", "last_changed": midnight.replace(hour=6).isoformat()},
        {"state": "3", "last_changed": measured_at.replace(minute=0).isoformat()},
    ]
    with (
        patch("backend.core.forecasts.datetime") as forecast_clock,
        patch("backend.core.ha_client.datetime") as initial_clock,
        patch("backend.core.prices.get_nordpool_data", new=AsyncMock(return_value=prices)),
        patch(
            "backend.core.forecasts.get_forecast_data", new=AsyncMock(return_value={"slots": []})
        ),
        patch("backend.core.ha_client.get_ha_sensor_kw_normalized", new=AsyncMock(return_value=3)),
        patch("backend.core.water_progress.LearningStore", return_value=store),
        patch(
            "backend.core.water_progress.get_power_history_batch",
            new=AsyncMock(return_value={"sensor.tank": history}),
        ) as reader,
    ):
        forecast_clock.now.return_value = measured_at
        initial_clock.now.return_value = measured_at
        initial_clock.fromisoformat.side_effect = datetime.fromisoformat
        inputs = await get_all_input_data(str(config_path))
    expected_cutoff = measured_at.replace(
        hour=12 if resolution_minutes == 30 else 13, minute=30 if resolution_minutes == 30 else 0
    )
    assert inputs["initial_state"]["water_progress_cutoff"] == expected_cutoff
    assert inputs["initial_state"]["water_heater_states"][0]["heated_today_kwh"] == pytest.approx(
        0.85
    )
    assert reader.await_args.args[2] == measured_at


@pytest.mark.parametrize("is_dst", [True, False])
@pytest.mark.asyncio
async def test_water_pipeline_runs_in_both_repeated_dst_hours(tmp_path, monkeypatch, is_dst):
    from planner.pipeline import PlannerPipeline
    from tests.fault_injection.test_dst_transitions import (
        make_inputs,
        next_transitions,
        planner_config,
    )

    monkeypatch.chdir(tmp_path)
    tz = pytz.timezone("Europe/Stockholm")
    _, fall = next_transitions()
    repeated_day = fall.astimezone(tz)
    now = tz.localize(
        datetime(repeated_day.year, repeated_day.month, repeated_day.day, 2, 45), is_dst=is_dst
    )
    config = planner_config()
    config.update(
        config_version=2,
        water_heating={"defer_up_to_hours": 2.5},
        water_heaters=[{"id": "tank", "power_kw": 3, "min_kwh_per_day": 1}],
    )
    config["system"].update(has_water_heater=True)
    inputs = make_inputs(now.astimezone(pytz.UTC), hours=6)
    inputs["initial_state"].update(
        water_progress_cutoff=now,
        water_heater_states=[
            {"id": "tank", "heated_today_kwh": 0.5, "progress_coverage": "partial"}
        ],
    )
    result = await PlannerPipeline(config).generate_schedule(
        inputs, mode="baseline", now_override=now, save_to_file=False, publish_state=False
    )
    assert not result.empty
    assert pd.Timestamp(result.index[0]) == pd.Timestamp(now)
