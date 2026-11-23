"""Price reserve uses measured forecast accuracy: de-biasing, noise gate and fallbacks."""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import pytz
from fastapi.testclient import TestClient

import planner.pipeline as pipeline_module
from backend.strategy import history
from backend.main import app
from ml.price_accuracy import load_forecast_accuracy
from planner.pipeline import PlannerPipeline, build_price_reserve_inputs, forecast_slot_horizons
from planner.strategy.ev_deferral import spot_to_import_price
from tests.planner.test_price_reserve_pipeline import (
    TZ,
    _df_for_inputs,
    captured_solves as captured_solves_fixture,
    future_base,
    make_forecast_db,
    make_full_inputs,
    reserve_config,
    run_full,
)

captured_solves = captured_solves_fixture  # reuse the pipeline tests' pytest fixture

K = 1.25  # 1 + VAT in reserve_config
FORECAST_SPOT = 0.9


def seed_accuracy(db: Path, horizon: int, errors: list[float], days: int = 3) -> None:
    """Paired forecast/actual rows of the last days: forecast = actual 1.0 + error."""
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS slot_observations "
        "(id INTEGER PRIMARY KEY, slot_start TEXT, export_price_sek_kwh REAL)"
    )
    for back in range(1, days + 1):
        for j, err in enumerate(errors):
            slot = (datetime.now(pytz.UTC) - timedelta(days=back)).replace(
                hour=6 + j, minute=0, second=0, microsecond=0
            )
            conn.execute(
                "INSERT INTO price_forecasts (slot_start, issue_timestamp, days_ahead, spot_p50) "
                "VALUES (?, 'old', ?, ?)",
                (slot.isoformat(), horizon, 1.0 + err),
            )
            conn.execute(
                "INSERT INTO slot_observations (slot_start, export_price_sek_kwh) VALUES (?, 1.0)",
                (slot.isoformat(),),
            )
    conn.commit()
    conn.close()


def setup(tmp_path: Path, *, days_ahead: int = 2):
    start = future_base()
    db = tmp_path / "learning.db"
    make_forecast_db(db, start, price=FORECAST_SPOT, evening=2.0, days_ahead=days_ahead)
    return start, db, reserve_config(db)


async def build(config, start, forecast_slots=None):
    df = _df_for_inputs(start)
    inputs = await build_price_reserve_inputs(
        config, df, df.index[0], df.index[-1], "Europe/Stockholm", 5.0, forecast_slots
    )
    assert inputs is not None
    return df, inputs


def unseen_cheap(inputs) -> float:
    return min(inputs.unseen_prices.values())


@pytest.mark.asyncio
async def test_unseen_prices_are_debiased_with_own_horizon(tmp_path):
    start, db, config = setup(tmp_path)
    _, plain = await build(config, start)  # no accuracy table at all
    seed_accuracy(db, 2, [0.38, 0.38])
    seed_accuracy(db, 1, [0.10, 0.10])  # other horizon must be ignored

    _, inputs = await build(config, start)

    assert inputs.accuracy_fallback is False
    assert inputs.forecast_bias_sek_kwh == pytest.approx(0.38)
    assert inputs.forecast_error_sek_kwh == pytest.approx(0.0)
    assert unseen_cheap(inputs) == pytest.approx(unseen_cheap(plain) - 0.38 * K)
    assert inputs.accuracy_by_horizon[2]["bias"] == pytest.approx(0.38)
    assert inputs.accuracy_by_horizon[2]["used_fallback"] is False


@pytest.mark.asyncio
async def test_matches_the_import_conversion(tmp_path):
    start, db, config = setup(tmp_path)
    seed_accuracy(db, 2, [0.38, 0.38])
    _, inputs = await build(config, start)
    slot = next(iter(inputs.unseen_prices))
    assert inputs.unseen_prices[slot] == pytest.approx(
        spot_to_import_price(FORECAST_SPOT - 0.38, config, slot)
    )


@pytest.mark.asyncio
async def test_typical_error_is_debiased_mae_in_import_domain(tmp_path):
    start, db, config = setup(tmp_path)
    seed_accuracy(db, 2, [0.68, 0.08])  # bias 0.38, de-biased MAE 0.30
    _, inputs = await build(config, start)
    assert inputs.forecast_bias_sek_kwh == pytest.approx(0.38)
    assert inputs.forecast_error_sek_kwh == pytest.approx(0.30 * K)


@pytest.mark.asyncio
async def test_endpoint_and_planner_agree(tmp_path):
    start, db, config = setup(tmp_path, days_ahead=1)  # planner reads the D+1 horizon
    seed_accuracy(db, 1, [0.5, 0.2, 0.9])
    _, inputs = await build(config, start)
    planner = load_forecast_accuracy(str(db), 1)
    assert inputs.forecast_bias_sek_kwh == planner.bias
    assert inputs.forecast_error_sek_kwh == pytest.approx((planner.debiased_mae or 0.0) * K)

    engine = MagicMock()
    engine.db_path = str(db)
    with (
        patch(
            "backend.api.routers.price_forecast._load_config",
            return_value={"price_forecast": {"enabled": True}},
        ),
        patch("backend.api.routers.price_forecast.get_learning_engine", return_value=engine),
    ):
        data = TestClient(app).get("/api/price-forecast/accuracy").json()

    assert data["status"] == "ok"
    assert data["d1_bias"] == round(planner.bias, 4)
    assert data["d1_mae"] == round(planner.mae, 4)
    assert data["sample_days"] == planner.sample_days


@pytest.mark.asyncio
async def test_missing_accuracy_table_keeps_todays_behaviour(tmp_path):
    start, _, config = setup(tmp_path)
    _, inputs = await build(config, start)
    assert inputs.error is None
    assert inputs.accuracy_fallback is True
    assert inputs.forecast_bias_sek_kwh == 0.0 and inputs.forecast_error_sek_kwh == 0.0
    assert inputs.corrected_known_slots == 0
    slot = next(iter(inputs.unseen_prices))
    assert inputs.unseen_prices[slot] == pytest.approx(
        spot_to_import_price(FORECAST_SPOT, config, slot)
    )


@pytest.mark.asyncio
async def test_insufficient_sample_days_is_not_corrected(tmp_path):
    start, db, config = setup(tmp_path)
    seed_accuracy(db, 2, [0.38, 0.38], days=1)
    _, inputs = await build(config, start)
    assert inputs.accuracy_fallback is True
    assert inputs.forecast_bias_sek_kwh == 0.0
    assert unseen_cheap(inputs) == pytest.approx(spot_to_import_price(FORECAST_SPOT, config))


@pytest.mark.asyncio
async def test_accuracy_read_exception_never_raises(tmp_path, monkeypatch):
    start, db, config = setup(tmp_path)
    seed_accuracy(db, 2, [0.38, 0.38])

    def boom(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("planner.pipeline.load_forecast_accuracy", boom)
    _, inputs = await build(config, start)
    assert inputs.error is None
    assert inputs.accuracy_fallback is True
    assert unseen_cheap(inputs) == pytest.approx(spot_to_import_price(FORECAST_SPOT, config))


@pytest.mark.asyncio
async def test_missing_own_horizon_falls_back_to_d1_then_none(tmp_path):
    start, db, config = setup(tmp_path)  # unseen rows are days_ahead 2
    seed_accuracy(db, 1, [0.20, 0.20])
    _, inputs = await build(config, start)
    assert inputs.forecast_bias_sek_kwh == pytest.approx(0.20)
    assert inputs.accuracy_by_horizon[2]["used_fallback"] is True
    assert unseen_cheap(inputs) == pytest.approx(spot_to_import_price(FORECAST_SPOT - 0.20, config))

    # Neither the own horizon nor D+1 has data: nothing is corrected.
    other = tmp_path / "other"
    other.mkdir()
    start2, db2, config2 = setup(other)
    seed_accuracy(db2, 5, [0.20, 0.20])
    _, none = await build(config2, start2)
    assert none.accuracy_fallback is True
    assert none.forecast_bias_sek_kwh == 0.0
    assert unseen_cheap(none) == pytest.approx(spot_to_import_price(FORECAST_SPOT, config2))


@pytest.mark.asyncio
async def test_pre_publication_known_forecast_slots_corrected_real_untouched(tmp_path):
    start, db, config = setup(tmp_path)
    seed_accuracy(db, 1, [0.20, 0.20])  # known forecast slots: horizon 1
    seed_accuracy(db, 2, [0.38, 0.38])  # unseen: horizon 2
    df = _df_for_inputs(start)
    before = df.copy()
    forecast_idx = list(df.index[24:48])  # D+1 forecast slots inside the known window
    mapping = {ts.to_pydatetime(): 1 for ts in forecast_idx}

    _, inputs = await build(config, start, mapping)

    prices = [s.price for s in inputs.known_slots]
    assert inputs.corrected_known_slots == 24
    assert prices[:24] == [0.8] * 24  # real slots untouched
    assert prices[24:48] == pytest.approx([0.8 - 0.20 * K] * 24)
    assert prices[48:] == [0.8] * (len(prices) - 48)
    pd.testing.assert_frame_equal(df, before)  # solver df unchanged
    assert inputs.accuracy_by_horizon[1]["bias"] == pytest.approx(0.20)
    assert inputs.accuracy_by_horizon[2]["bias"] == pytest.approx(0.38)


@pytest.mark.asyncio
async def test_pre_issue_horizons_two_and_three(tmp_path):
    start, db, config = setup(tmp_path, days_ahead=3)  # unseen from yesterday's issue
    seed_accuracy(db, 2, [0.25, 0.25])
    seed_accuracy(db, 3, [0.45, 0.45])
    df = _df_for_inputs(start)
    mapping = {ts.to_pydatetime(): 2 for ts in df.index[24:48]}

    _, inputs = await build(config, start, mapping)

    prices = [s.price for s in inputs.known_slots]
    assert prices[24:48] == pytest.approx([0.8 - 0.25 * K] * 24)
    assert unseen_cheap(inputs) == pytest.approx(spot_to_import_price(FORECAST_SPOT - 0.45, config))
    assert set(inputs.accuracy_by_horizon) == {2, 3}


@pytest.mark.asyncio
async def test_gate_uses_largest_debiased_mae_of_used_horizons(tmp_path):
    start, db, config = setup(tmp_path)
    seed_accuracy(db, 1, [0.50, 0.10])  # de-biased MAE 0.20
    seed_accuracy(db, 2, [0.40, 0.20])  # de-biased MAE 0.10
    seed_accuracy(db, 3, [1.50, 0.50])  # not used
    df = _df_for_inputs(start)
    mapping = {df.index[30].to_pydatetime(): 1}

    _, inputs = await build(config, start, mapping)
    assert inputs.forecast_error_sek_kwh == pytest.approx(0.20 * K)

    _, only_unseen = await build(config, start)
    assert only_unseen.forecast_error_sek_kwh == pytest.approx(0.10 * K)


def test_forecast_slot_horizons_default_and_filter():
    ts = [datetime(2030, 1, 1, h, 0, tzinfo=pytz.UTC) for h in range(4)]
    data = [
        {"start_time": ts[0], "price_source": "nordpool"},
        {"start_time": ts[1], "price_source": "forecast", "forecast_days_ahead": 2},
        {"start_time": ts[2], "price_source": "forecast"},  # key absent -> horizon 1
        {"start_time": ts[3], "price_source": "forecast", "forecast_days_ahead": "x"},
        {"start_time": None, "price_source": "forecast"},
    ]
    got = forecast_slot_horizons(data, "Europe/Stockholm")
    assert {k.astimezone(pytz.UTC): v for k, v in got.items()} == {ts[1]: 2, ts[2]: 1, ts[3]: 1}


@pytest.fixture
def reserve_debug(monkeypatch):
    """Capture the safety-floor debug dict the pipeline hands to the reserve event."""
    captured: list[dict] = []
    monkeypatch.setattr(pipeline_module, "_log_price_reserve_event", captured.append)
    return captured


@pytest.mark.asyncio
async def test_full_run_bias_only_gap_gives_no_reserve(tmp_path, monkeypatch, reserve_debug):
    start, db, config = setup(tmp_path)
    # Published prices equal the true level of the unseen cheap hours (forecast 0.9 is 0.38 high).
    true_import = spot_to_import_price(FORECAST_SPOT - 0.38, config)

    def inputs_at_true_level() -> dict:
        inputs = make_full_inputs(start)
        for entry in inputs["price_data"]:
            entry["import_price_sek_kwh"] = true_import
        return inputs

    async def run(cfg) -> dict:
        await PlannerPipeline(cfg).generate_schedule(
            inputs_at_true_level(),
            mode="full",
            save_to_file=False,
            now_override=start.astimezone(TZ),
        )
        return reserve_debug[-1]

    # Control: no accuracy data, the bias is mistaken for a real gap and a reserve is sized.
    assert (await run(config))["price_reserve_kwh"] > 0.0

    seed_accuracy(db, 2, [0.38, 0.38])  # forecast always 0.38 too high
    debug = await run(config)

    assert debug["price_reserve_kwh"] == 0.0
    assert debug["price_reserve_reason"] == "own_day_cheaper"
    assert debug["price_reserve_forecast_bias_sek_kwh"] == pytest.approx(0.38)
    assert debug["price_reserve_accuracy_fallback"] is False
    assert debug["price_reserve_effective_threshold_sek"] == pytest.approx(0.10)
    assert debug["price_reserve_threshold_sek"] == pytest.approx(0.10)
    assert debug["price_reserve_corrected_known_slots"] == 0
    assert debug["price_reserve_forecast_accuracy"][2]["bias"] == pytest.approx(0.38)


@pytest.mark.asyncio
async def test_full_run_accurate_forecast_reserves_as_before(
    tmp_path, monkeypatch, captured_solves, reserve_debug
):
    start, db, config = setup(tmp_path)
    seed_accuracy(db, 2, [0.01, -0.01])

    await run_full(config, start)

    debug = reserve_debug[0]
    assert debug["price_reserve_reason"] == "active"
    assert debug["price_reserve_kwh"] == pytest.approx(6.0 / 0.95, abs=0.01)
    assert debug["price_reserve_accuracy_fallback"] is False
    assert debug["price_reserve_forecast_error_sek_kwh"] == pytest.approx(0.01 * K, abs=1e-3)
    assert captured_solves[0].target_soc_kwh == pytest.approx(0.15 * 27.0 + 6.0 / 0.95, abs=0.05)


@pytest.mark.asyncio
async def test_full_run_without_accuracy_data_reports_fallback(
    tmp_path, monkeypatch, reserve_debug
):
    start, _, config = setup(tmp_path)

    await run_full(config, start)

    debug = reserve_debug[0]
    assert debug["price_reserve_reason"] == "active"
    assert debug["price_reserve_accuracy_fallback"] is True
    assert debug["price_reserve_forecast_bias_sek_kwh"] == 0.0
    assert debug["price_reserve_forecast_error_sek_kwh"] == 0.0
    assert debug["price_reserve_effective_threshold_sek"] == pytest.approx(0.10)
    assert debug["price_reserve_forecast_accuracy"] == {
        2: {"bias": 0.0, "debiased_mae": 0.0, "sample_days": 0, "used_fallback": True}
    }


@pytest.mark.asyncio
async def test_full_run_forecast_known_slots_are_corrected_not_the_solver_prices(
    tmp_path, monkeypatch, reserve_debug
):
    start, db, config = setup(tmp_path)
    seed_accuracy(db, 1, [0.20, 0.20])
    seed_accuracy(db, 2, [0.38, 0.38])
    inputs = make_full_inputs(start)
    for entry in inputs["price_data"][8:16]:
        entry["price_source"] = "forecast"
        entry["forecast_days_ahead"] = 1
    original_prices = [e["import_price_sek_kwh"] for e in inputs["price_data"]]

    pipeline = PlannerPipeline(config)
    await pipeline.generate_schedule(
        inputs, mode="full", save_to_file=False, now_override=start.astimezone(TZ)
    )

    debug = reserve_debug[0]
    assert debug["price_reserve_corrected_known_slots"] == 8
    assert [e["import_price_sek_kwh"] for e in inputs["price_data"]] == original_prices


def test_strategy_event_carries_accuracy_details(tmp_path, monkeypatch):
    accuracy = {2: {"bias": 0.38, "debiased_mae": 0.1, "sample_days": 3, "used_fallback": False}}
    pipeline_module._log_price_reserve_event(
        {
            "price_reserve_applied_kwh": 6.0,
            "price_reserve_kwh": 6.0,
            "price_reserve_reason": "active",
            "known_cost_sek_kwh": 1.0,
            "own_day_cost_sek_kwh": 1.5,
            "price_reserve_threshold_sek": 0.1,
            "price_reserve_effective_threshold_sek": 0.125,
            "price_reserve_forecast_bias_sek_kwh": 0.38,
            "price_reserve_forecast_error_sek_kwh": 0.125,
            "price_reserve_accuracy_fallback": False,
            "price_reserve_forecast_accuracy": accuracy,
            "price_reserve_corrected_known_slots": 24,
        }
    )

    (event,) = json.loads(history.HISTORY_FILE.read_text())
    assert "+0.38" in event["message"]
    assert "0.12" in event["message"]
    details = event["details"]
    assert details["price_reserve_forecast_bias_sek_kwh"] == 0.38
    assert details["price_reserve_effective_threshold_sek"] == 0.125
    assert details["price_reserve_forecast_error_sek_kwh"] == 0.125
    assert details["price_reserve_accuracy_fallback"] is False
    assert details["price_reserve_corrected_known_slots"] == 24
