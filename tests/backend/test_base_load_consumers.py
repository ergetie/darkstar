"""Every base-load consumer skips (or nulls) slots flagged `base_load.reliable == false`."""

import json
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_asyncio
import pytz

from backend.api.routers import forecast as forecast_router
from backend.api.routers.energy import _base_load_avg_daily_kwh
from backend.learning.models import Base
from backend.learning.store import LearningStore
from ml.forward import determine_graduation_level
from ml.load_clean import clean_load_observations

TZ = pytz.timezone("Europe/Stockholm")
NOW = TZ.localize(datetime(2026, 9, 25, 12, 7))
CURRENT_SLOT = TZ.localize(datetime(2026, 9, 25, 12, 0))
RELIABLE = json.dumps({"source": "recorder"})
FLAGGED = json.dumps(
    {"source": "recorder", "base_load": {"reliable": False, "reasons": ["device_partial_coverage"]}}
)
LEGACY_FLAGGED = json.dumps(
    {"base_load": {"reliable": False, "reasons": ["legacy_counter_clamp"], "source": "migration"}}
)


@pytest_asyncio.fixture
async def store(tmp_path):
    store = LearningStore(str(tmp_path / "learning.db"), TZ)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield store
    await store.close()


def _insert(store: LearningStore, starts: list[datetime], flags: str | None, load=0.25, fv=None):
    con = sqlite3.connect(store.db_path)
    for start in starts:
        con.execute(
            "INSERT INTO slot_observations (slot_start, slot_end, load_kwh, import_kwh, "
            "quality_flags) VALUES (?, ?, ?, 0.5, ?)",
            (start.isoformat(), (start + timedelta(minutes=15)).isoformat(), load, flags),
        )
        if fv:
            con.execute(
                "INSERT INTO slot_forecasts (slot_start, load_forecast_kwh, forecast_version) "
                "VALUES (?, 1.0, ?)",
                (start.isoformat(), fv),
            )
    con.commit()
    con.close()


def _completed(n: int, offset: int = 0) -> list[datetime]:
    return [CURRENT_SLOT - timedelta(minutes=15 * (i + 1 + offset)) for i in range(n)]


@pytest.mark.asyncio
async def test_base_load_daily_average_ignores_flagged_slots(store):
    _insert(store, _completed(96), RELIABLE, load=0.25)
    _insert(store, _completed(20, offset=96), LEGACY_FLAGGED, load=9.0)
    assert await _base_load_avg_daily_kwh(store, NOW) == pytest.approx(24.0)


@pytest.mark.asyncio
async def test_flagged_slots_are_too_few_to_report_an_average(store):
    _insert(store, _completed(96), FLAGGED, load=0.25)
    assert await _base_load_avg_daily_kwh(store, NOW) is None


@pytest.mark.asyncio
async def test_load_mae_only_uses_reliable_slots(store):
    now = datetime.now(TZ).replace(minute=0, second=0, microsecond=0)
    good, bad = now - timedelta(minutes=30), now - timedelta(minutes=15)
    _insert(store, [good], RELIABLE, load=0.5, fv="aurora")
    _insert(store, [bad], FLAGGED, load=0.0, fv="aurora")
    metrics = await store.calculate_metrics(days_back=1)
    assert metrics["mae_load"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_observation_range_hides_the_placeholder_load(store):
    start = CURRENT_SLOT - timedelta(minutes=30)
    _insert(store, [start], FLAGGED, load=0.0)
    _insert(store, [start + timedelta(minutes=15)], RELIABLE, load=0.4)
    rows = await store.get_observations_range(start, start + timedelta(hours=1))
    assert [row["load_kwh"] for row in rows] == [None, 0.4]


@pytest.mark.asyncio
async def test_chart_actuals_are_null_for_flagged_slots(store):
    start = datetime.now(TZ).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    _insert(store, [start], FLAGGED, load=0.0, fv="aurora")
    _insert(store, [start + timedelta(minutes=15)], RELIABLE, load=0.4, fv="aurora")
    engine = SimpleNamespace(store=store)
    history = await forecast_router._get_history_with_actuals(
        engine, start - timedelta(minutes=1), start + timedelta(hours=1)
    )
    assert [slot["actual"] for slot in history["load"] if slot["forecast"] is not None] == [
        None,
        0.4,
    ]

    with (
        patch.object(forecast_router, "get_learning_engine", return_value=engine),
        patch.object(forecast_router, "_get_timezone", return_value=TZ),
    ):
        payload = await forecast_router.forecast_day(start.date().isoformat())
    actual = {slot["slot_start"]: slot["actual_load"] for slot in payload["slots"]}
    assert actual[start.isoformat()] is None
    assert actual[(start + timedelta(minutes=15)).isoformat()] == 0.4


def test_graduation_level_counts_only_days_with_reliable_load(tmp_path):
    db = str(tmp_path / "grad.db")
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE slot_observations (slot_start TEXT PRIMARY KEY, load_kwh REAL, "
        "quality_flags TEXT)"
    )
    con.execute(
        "CREATE TABLE slot_forecasts (slot_start TEXT, load_forecast_kwh REAL, "
        "forecast_version TEXT)"
    )
    today = datetime.now(TZ).replace(hour=12, minute=0, second=0, microsecond=0)
    for day in range(1, 21):
        slot = (today - timedelta(days=day)).isoformat()
        flags = FLAGGED if day > 5 else RELIABLE
        con.execute("INSERT INTO slot_observations VALUES (?, 0.3, ?)", (slot, flags))
        con.execute("INSERT INTO slot_forecasts VALUES (?, 0.3, 'aurora')", (slot,))
    con.commit()
    con.close()
    engine = SimpleNamespace(db_path=db, timezone=TZ)
    level, label, days = determine_graduation_level(engine)  # type: ignore[arg-type]
    assert (level, label, days) == (1, "statistician", 5.0)


def test_training_data_drops_recorder_and_legacy_flagged_rows():
    import pandas as pd

    index = pd.date_range(TZ.localize(datetime(2026, 11, 2)), periods=4, freq="15min", tz=TZ)
    frame = pd.DataFrame(
        {
            "slot_start": index,
            "load_kwh": [0.4, 0.0, 0.0, 0.4],
            "import_kwh": 0.3,
            "pv_kwh": 0.0,
            "batt_discharge_kwh": 0.0,
            "quality_flags": [RELIABLE, FLAGGED, LEGACY_FLAGGED, None],
        }
    )
    clean, stats = clean_load_observations(frame)
    assert list(clean["load_kwh"]) == [0.4, 0.4]
    assert stats["dropped_unmeasured_device_rows"] == 2


def _recording_flags(**methods: str) -> str:
    components = {name: {"method": method, "owner": "recorder"} for name, method in methods.items()}
    recording = {
        "schema_version": 1,
        "semantics": "slot-energy-v1",
        "boundary_fingerprint": "a" * 64,
        "components": components,
        "soc": {"source": "live", "owner": "recorder"},
    }
    return json.dumps({"recording": recording})


@pytest.mark.parametrize(
    ("flags", "counted"),
    [
        (_recording_flags(water="unconfigured_zero", ev="unconfigured_zero"), True),
        (_recording_flags(water="disabled_zero", ev="power_history"), True),
        (_recording_flags(water="unknown"), False),
        (_recording_flags(ev="snapshot"), False),
        (_recording_flags(water="mixed"), False),
        (_recording_flags(load="unknown"), False),
        (None, True),
    ],
)
def test_graduation_mirrors_the_training_predicate(tmp_path, flags, counted):
    """Graduation counts exactly the days load training keeps (same unmeasured-device rule)."""
    import pandas as pd

    db = str(tmp_path / "grad.db")
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE slot_observations (slot_start TEXT PRIMARY KEY, load_kwh REAL, "
        "quality_flags TEXT)"
    )
    con.execute(
        "CREATE TABLE slot_forecasts (slot_start TEXT, load_forecast_kwh REAL, "
        "forecast_version TEXT)"
    )
    today = datetime.now(TZ).replace(hour=12, minute=0, second=0, microsecond=0)
    slot = (today - timedelta(days=2)).isoformat()
    con.execute("INSERT INTO slot_observations VALUES (?, 0.3, ?)", (slot, flags))
    con.execute("INSERT INTO slot_forecasts VALUES (?, 0.3, 'aurora')", (slot,))
    con.commit()
    con.close()

    _, _, days = determine_graduation_level(SimpleNamespace(db_path=db, timezone=TZ))  # type: ignore[arg-type]
    assert days == (1.0 if counted else 0.0)

    frame = pd.DataFrame(
        {
            "slot_start": [pd.Timestamp(slot)],
            "load_kwh": [0.3],
            "import_kwh": [0.3],
            "pv_kwh": [0.0],
            "batt_discharge_kwh": [0.0],
            "quality_flags": [flags],
        }
    )
    clean, _ = clean_load_observations(frame)
    assert (len(clean) == 1) == counted
