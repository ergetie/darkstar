"""ev-charging-losses 5.2: Reflex learns EV loss parameters per charger."""

import contextlib
import random
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
import pytz
from ruamel.yaml import YAML

from backend.learning.models import Base, EvChargerObservation
from backend.learning.reflex import AuroraReflex
from backend.learning.store import LearningStore

TZ = pytz.timezone("Europe/Stockholm")
TRUE = {"charge_efficiency": 0.92, "charge_overhead_kw": 0.3, "start_loss_kwh": 0.2}


@pytest_asyncio.fixture
async def store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    store = LearningStore(db_path, TZ)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield store
    await store.close()
    with contextlib.suppress(OSError):
        Path(db_path).unlink()


async def _seed(
    store, days: int, params: dict[str, float], source: str = "sensor", first_day: int = 1
) -> None:
    """Days with 2-3 sessions of varying length and power, car energy from ``params``."""
    rng = random.Random(42)
    today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    async with store.AsyncSession() as session:
        for d in range(first_day, first_day + days):
            day = today - timedelta(days=d)
            hour = 1
            for _ in range(rng.choice((2, 3))):
                n_slots = rng.randint(2, 12)
                power_kw = rng.choice((2.3, 4.1, 7.0, 11.0))
                for i in range(n_slots):
                    start = day + timedelta(hours=hour, minutes=15 * i)
                    wall = power_kw * 0.25
                    car = (
                        params["charge_efficiency"] * wall
                        - params["charge_overhead_kw"] * 0.25
                        - (params["start_loss_kwh"] if i == 0 else 0.0)
                    )
                    session.add(
                        EvChargerObservation(
                            slot_start=start.isoformat(),
                            charger_id="goe",
                            energy_kwh=wall,
                            car_energy_kwh=car,
                            car_energy_source=source,
                        )
                    )
                hour += 4
        await session.commit()


def _reflex(store, charger: dict, enabled: bool = True) -> AuroraReflex:
    with patch.object(AuroraReflex, "__init__", lambda self, path: None):
        reflex = AuroraReflex.__new__(AuroraReflex)
    reflex.config = {
        "learning": {"reflex_enabled": enabled},
        "ev_chargers": [{"id": "goe", "enabled": True, **charger}],
    }
    reflex.store = store
    reflex.timezone = TZ
    reflex.learning_engine = MagicMock()
    return reflex


@pytest.mark.asyncio
async def test_not_enough_data_no_change(store):
    await _seed(store, days=5, params=TRUE)
    updates, report = await _reflex(store, {}).analyze_ev_losses()
    assert updates == {}
    assert "Insufficient data (5 clean days" in report[0]


@pytest.mark.asyncio
async def test_synthetic_data_recovers_parameters(store):
    await _seed(store, days=12, params=TRUE)
    reflex = _reflex(store, {})
    days, _ = await reflex._ev_loss_days("goe")
    assert len(days) == 12
    # Starting next to the truth, the daily step lands on the fitted values.
    near = {k: v + 0.005 for k, v in TRUE.items()}
    updates, report = await _reflex(store, near).analyze_ev_losses()
    for key, value in TRUE.items():
        assert updates[f"ev_chargers.goe.{key}"] == pytest.approx(value, abs=1e-3)
    assert "12 days" in report[0]


@pytest.mark.asyncio
async def test_daily_max_change_from_defaults(store):
    await _seed(store, days=12, params=TRUE)
    updates, _ = await _reflex(store, {}).analyze_ev_losses()
    # Defaults 0.95 / 0.25 / 0.15 move one daily step towards the fit.
    assert updates["ev_chargers.goe.charge_efficiency"] == pytest.approx(0.94)
    assert updates["ev_chargers.goe.charge_overhead_kw"] == pytest.approx(0.3)
    assert updates["ev_chargers.goe.start_loss_kwh"] == pytest.approx(0.18)


@pytest.mark.asyncio
async def test_bounds_clamped(store):
    await _seed(store, days=12, params={**TRUE, "charge_overhead_kw": 1.5})
    updates, _ = await _reflex(store, {"charge_overhead_kw": 0.98}).analyze_ev_losses()
    assert updates["ev_chargers.goe.charge_overhead_kw"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_soc_data_ignored_when_sensor_data_exists(store):
    await _seed(store, days=12, params=TRUE, source="soc")
    days, _ = await _reflex(store, {})._ev_loss_days("goe")
    assert len(days) == 12  # SoC-only history is used
    await _seed(store, days=3, params=TRUE, source="sensor", first_day=13)
    days, _ = await _reflex(store, {})._ev_loss_days("goe")
    assert len(days) == 3  # sensor history wins once it exists


@pytest.mark.asyncio
async def test_reflex_disabled_changes_nothing(store):
    await _seed(store, days=12, params=TRUE)
    reflex = _reflex(store, {}, enabled=False)
    with patch.object(AuroraReflex, "update_config") as update:
        result = await reflex.run()
    assert result == ["Skipped: Reflex disabled"]
    update.assert_not_called()


@pytest.mark.asyncio
async def test_update_config_writes_into_charger_entry(store, tmp_path):
    config_path = tmp_path / "config.yaml"
    default = YAML().load(Path(__file__).resolve().parents[2] / "config.default.yaml")
    template = dict(default["ev_chargers"][0])
    default["ev_chargers"] = [{**template, "id": "other"}, {**template, "id": "goe"}]
    with config_path.open("w", encoding="utf-8") as handle:
        YAML().dump(default, handle)
    reflex = _reflex(store, {})
    reflex.config_path = config_path
    reflex.yaml = YAML()
    with patch("backend.learning.reflex.append_strategy_event"):
        await reflex.update_config({"ev_chargers.goe.charge_overhead_kw": 0.3}, dry_run=False)
    data = YAML().load(config_path.read_text())
    assert data["ev_chargers"][1]["charge_overhead_kw"] == 0.3
    assert data["ev_chargers"][0]["charge_overhead_kw"] == 0.25
    assert "ev_chargers" in data and len(data["ev_chargers"]) == 2
