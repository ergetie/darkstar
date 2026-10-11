"""ev-charging-losses 3.1 / 4.2 / 4.3: car-side energy recording and goal accounting."""

from datetime import datetime, timedelta
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
)
from planner.pipeline import _calculate_required_kwh, _ev_delivered_today_kwh

TZ = pytz.timezone("Europe/Stockholm")
START = TZ.localize(datetime(2026, 10, 11, 10, 0))
END = START + timedelta(minutes=15)


def _states(*points: tuple[datetime, str]) -> list[dict]:
    return [{"state": v, "last_changed": ts.isoformat()} for ts, v in points]


class TestCarEnergyHelpers:
    def test_sensor_reset_mid_slot(self):
        states = _states(
            (START, "24.8"), (START + timedelta(minutes=5), "0"), (END, "0.6")
        )
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
