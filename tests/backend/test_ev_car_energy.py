"""ev-charging-losses 3.1 / 4.2 / 4.3: car-side energy recording and goal accounting."""

from datetime import datetime, timedelta
from itertools import pairwise
from unittest.mock import patch

import pandas as pd
import pytest
import pytest_asyncio
import pytz
from sqlalchemy import select

from backend.learning.models import Base, EvChargerObservation
from backend.learning.store import LearningStore
from backend.recorder import (
    _ev_car_energy,
    car_energy_from_added_sensor,
    car_energy_from_soc,
    zero_rejected_ev_energy,
)
from planner.pipeline import _calculate_required_kwh, _ev_delivered_today_kwh

TZ = pytz.timezone("Europe/Stockholm")
START = TZ.localize(datetime(2026, 10, 11, 10, 0))
END = START + timedelta(minutes=15)
IDLE_WALLBOX = 7.5e-05
DRIFT = [22.58, 22.47, 22.36, 22.25, 22.14, 22.03, 21.92]


def _states(*points: tuple[datetime, str]) -> list[dict]:
    return [{"state": v, "last_changed": ts.isoformat()} for ts, v in points]


def _charger(**extra):
    return {"ev_chargers": [{"id": "ev1", "energy_added_sensor": "sensor.added", **extra}]}


def _car(config, wallbox, first, last):
    history = {"sensor.added": _states((START, str(first)), (END, str(last)))}
    return _ev_car_energy(config, {"ev1": wallbox}, history, START, END)["ev1"]["kwh"]


class TestCarEnergyHelpers:
    def test_sensor_reset_mid_slot(self):
        states = _states((START, "24.8"), (START + timedelta(minutes=5), "0"), (END, "0.6"))
        assert car_energy_from_added_sensor(states) == pytest.approx(0.6)

    def test_sensor_plain_delta(self):
        states = _states((START, "3.0"), (START + timedelta(minutes=7), "4.1"))
        assert car_energy_from_added_sensor(states) == pytest.approx(1.1)

    def test_sensor_unavailable_is_none(self):
        assert car_energy_from_added_sensor(_states((START, "unavailable"))) is None
        assert car_energy_from_added_sensor([]) is None

    def test_soc_fallback(self):
        states = _states((START, "60"), (END - timedelta(minutes=2), "62"))
        assert car_energy_from_soc(states, 64.0, START, END, 15) == pytest.approx(1.28)

    def test_stale_soc_is_none(self):
        # End reading unavailable
        states = _states((START, "60"), (END - timedelta(minutes=1), "unavailable"))
        assert car_energy_from_soc(states, 64.0, START, END, 15) is None
        # Last reading too old for the slot end
        states = _states((START - timedelta(minutes=40), "60"))
        assert car_energy_from_soc(states, 64.0, START, END, 15) is None
        # First reading too late for the slot start
        states = _states((START + timedelta(minutes=8), "60"), (END, "61"))
        assert car_energy_from_soc(states, 64.0, START, END, 5) is None

    def test_sensor_preferred_and_soc_only_without_sensor(self):
        config = {
            "ev_chargers": [
                {"id": "a", "energy_added_sensor": "sensor.added", "soc_sensor": "sensor.soc"},
                {"id": "b", "soc_sensor": "sensor.soc_b", "battery_capacity_kwh": 64.0},
                {"id": "c"},
            ]
        }
        history = {
            "sensor.added": _states((START, "1.0"), (END, "2.0")),
            "sensor.soc": _states((START, "10"), (END, "90")),
            "sensor.soc_b": _states((START, "60"), (END, "62")),
        }
        result = _ev_car_energy(config, {"a": 1.1, "b": 1.4, "c": 0.5}, history, START, END)
        assert result["a"] == {"kwh": pytest.approx(1.0), "source": "sensor"}
        assert result["b"] == {"kwh": pytest.approx(1.28), "source": "soc"}
        assert "c" not in result

    def test_idle_drift_is_zero_per_slot(self):
        """torleif sequence: each drop used to be booked as the whole new value."""
        for prev, cur in pairwise(DRIFT):
            assert car_energy_from_added_sensor(_states((START, str(prev)), (END, str(cur)))) == 0.0
            assert _car(_charger(), IDLE_WALLBOX, prev, cur) == 0.0

    def test_genuine_reset_counts(self):
        states = _states((START, "24.8"), (START + timedelta(minutes=5), "0"), (END, "0.6"))
        assert car_energy_from_added_sensor(states) == pytest.approx(0.6)
        history = {"sensor.added": states}
        result = _ev_car_energy(_charger(), {"ev1": 0.7}, history, START, END)
        assert result["ev1"]["kwh"] == pytest.approx(0.6)

    def test_non_zero_drop_ignored_then_rise_counts(self):
        states = _states((START, "22.4"), (START + timedelta(minutes=5), "3.0"), (END, "3.8"))
        assert car_energy_from_added_sensor(states) == pytest.approx(0.8)

    def test_reset_threshold_is_configurable(self):
        states = _states((START, "10.0"), (END, "1.0"))
        assert car_energy_from_added_sensor(states) == 0.0
        assert car_energy_from_added_sensor(states, 2.0) == pytest.approx(1.0)
        config = _charger(energy_added_reset_threshold_kwh=2.0)
        assert _car(config, 1.2, 10.0, 1.0) == pytest.approx(1.0)

    def test_wallbox_cap(self):
        assert _car(_charger(), 1.0, 1.0, 3.0) == pytest.approx(1.05)
        assert _car(_charger(), IDLE_WALLBOX, 5.0, 5.77) == 0.0
        assert _car(_charger(), 0.1382, 5.0, 5.44) == pytest.approx(0.1882)
        assert _car(_charger(), 0.4397, 5.0, 5.44) == pytest.approx(0.44)

    def test_rejected_aggregate_zeroes_car_energy(self):
        record = {
            "ev_charging_kwh": 0,
            "ev_charger_energy": {"ev1": 99.0},
            "ev_charger_car_energy": {"ev1": {"kwh": 22.4, "source": "sensor"}},
        }
        out = zero_rejected_ev_energy(record)
        assert out["ev_charger_energy"] == {"ev1": 0.0}
        assert out["ev_charger_car_energy"] == {"ev1": {"kwh": 0.0, "source": "sensor"}}

    def test_valid_aggregate_untouched(self):
        record = {
            "ev_charging_kwh": 1.0,
            "ev_charger_energy": {"ev1": 1.0},
            "ev_charger_car_energy": {"ev1": {"kwh": 0.9, "source": "sensor"}},
        }
        assert zero_rejected_ev_energy(record)["ev_charger_car_energy"]["ev1"]["kwh"] == 0.9


@pytest_asyncio.fixture
async def store(tmp_path):
    store = LearningStore(str(tmp_path / "learning.db"), TZ)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield store
    await store.close()


def _record(start: datetime, wall: dict[str, float], car: dict | None) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "slot_start": start,
                "slot_end": start + timedelta(minutes=15),
                "import_kwh": 1.0,
                "ev_charging_kwh": sum(wall.values()),
                "ev_charger_energy": wall,
                "ev_charger_car_energy": car,
            }
        ]
    )


@pytest.mark.asyncio
async def test_store_persists_car_energy(store):
    await store.store_slot_observations(
        _record(START, {"ev1": 1.5, "ev2": 1.0}, {"ev1": {"kwh": 1.3, "source": "sensor"}})
    )
    async with store.AsyncSession() as session:
        rows = (
            await session.execute(
                select(
                    EvChargerObservation.charger_id,
                    EvChargerObservation.car_energy_kwh,
                    EvChargerObservation.car_energy_source,
                ).order_by(EvChargerObservation.charger_id)
            )
        ).all()
    assert [tuple(r) for r in rows] == [("ev1", 1.3, "sensor"), ("ev2", None, None)]


@pytest.mark.asyncio
async def test_delivered_uses_car_energy_else_wall_times_efficiency(store):
    await store.store_slot_observations(
        _record(START, {"ev1": 2.0}, {"ev1": {"kwh": 1.7, "source": "sensor"}})
    )
    await store.store_slot_observations(_record(END, {"ev1": 10.0}, None))
    now = START + timedelta(hours=2)
    assert _ev_delivered_today_kwh(store.db_path, "ev1", TZ, now, 0.9) == pytest.approx(10.7)


def test_required_fallback_counts_wall_times_efficiency(tmp_path):
    """Spec: no SoC, 10 kWh wall recorded without car energy, efficiency 0.9 -> 9 kWh."""
    cfg = {
        "id": "ev1",
        "target_soc_percent": 80,
        "battery_capacity_kwh": 60.0,
        "charge_efficiency": 0.9,
    }
    with patch("planner.pipeline._ev_delivered_today_kwh", return_value=9.0) as mock_delivered:
        required = _calculate_required_kwh(cfg, {"soc_percent": None}, "some.db", TZ)
    assert mock_delivered.call_args.args[4] == 0.9
    assert required == pytest.approx(48.0 - 9.0)


@pytest.mark.asyncio
async def test_delivered_today_caps_legacy_bad_rows(store):
    """Legacy rows with phantom ~22 kWh car energy no longer inflate delivered today."""
    for i, car in enumerate([22.47, 22.36, 22.25, 0.0]):
        start = START + timedelta(minutes=15 * i)
        entry = {"kwh": car, "source": "sensor"}
        await store.store_slot_observations(_record(start, {"ev1": IDLE_WALLBOX}, {"ev1": entry}))
    now = START + timedelta(hours=3)
    assert _ev_delivered_today_kwh(store.db_path, "ev1", TZ, now, 0.95) < 0.5


async def _store_charged_slots(store, steps):
    """Record each (prev, cur, wallbox) step through the recorder into the store."""
    config = _charger()
    for i, (prev, cur, wallbox) in enumerate(steps):
        start = START + timedelta(minutes=15 * i)
        end = start + timedelta(minutes=15)
        history = {"sensor.added": _states((start, str(prev)), (end, str(cur)))}
        entry = _ev_car_energy(config, {"ev1": wallbox}, history, start, end)["ev1"]
        await store.store_slot_observations(_record(start, {"ev1": wallbox}, {"ev1": entry}))


@pytest.mark.asyncio
async def test_torleif_sequence_end_to_end(store):
    """Recorder -> DB -> _ev_delivered_today_kwh for the 2026-10-18 idle drift."""
    steps = [(prev, cur, IDLE_WALLBOX) for prev, cur in pairwise(DRIFT)]
    await _store_charged_slots(store, steps)
    now = START + timedelta(hours=3)
    delivered = _ev_delivered_today_kwh(store.db_path, "ev1", TZ, now, 0.95)
    assert delivered == pytest.approx(0.0, abs=1e-6)


@pytest.mark.asyncio
async def test_real_session_then_reset_is_counted(store):
    """Car energy below wallbox energy is not capped; a reset to ~0 then a new session counts."""
    steps = [(0.0, 1.0, 1.0), (1.0, 2.9, 2.0), (2.9, 0.0, 0.0), (0.0, 0.8, 0.9)]
    await _store_charged_slots(store, steps)
    now = START + timedelta(hours=3)
    delivered = _ev_delivered_today_kwh(store.db_path, "ev1", TZ, now, 0.95)
    assert delivered == pytest.approx(1.0 + 1.9 + 0.0 + 0.8)
