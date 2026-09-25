"""Unit tests for planner/preflight.py — one failing and one passing case per check."""
from __future__ import annotations

import math
import logging
from datetime import datetime, timedelta, timezone

import pytest

from planner.errors import PlannerError, PlannerErrorCode
from planner.preflight import (
    SOC_STALENESS_WARNING_MINUTES,
    check_battery_config,
    check_ev_chargers,
    check_ev_deadlines,
    check_forecast_data,
    check_initial_soc,
    check_numeric_sanity,
    check_price_data,
    check_soc_staleness,
    run_preflight,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _price_slot(start: datetime, hours: float = 1.0) -> dict:
    end = start + timedelta(hours=hours)
    return {
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "import_price_sek_kwh": 1.0,
        "export_price_sek_kwh": 0.5,
    }


def _forecast_slot(start: datetime, hours: float = 1.0) -> dict:
    end = start + timedelta(hours=hours)
    return {
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "pv_forecast_kwh": 0.5,
        "load_forecast_kwh": 0.3,
    }


def _valid_config(**battery_overrides) -> dict:
    battery = dict(
        capacity_kwh=10.0,
        min_soc_percent=10.0,
        max_soc_percent=90.0,
        max_charge_w=5000,
        max_discharge_w=5000,
    )
    battery.update(battery_overrides)
    return {"system": {"has_battery": True}, "battery": battery, "ev_chargers": []}


def _valid_input(initial_soc_kwh: float = 5.0, future_hours: int = 8) -> dict:
    now = _now()
    prices = [_price_slot(now + timedelta(hours=i)) for i in range(future_hours)]
    forecasts = [_forecast_slot(now + timedelta(hours=i)) for i in range(future_hours)]
    return {
        "price_data": prices,
        "forecast_data": forecasts,
        "initial_state": {"battery_kwh": initial_soc_kwh},
    }


# --- check_battery_config ---

def test_battery_config_invalid_soc_range():
    config = _valid_config(min_soc_percent=50.0, max_soc_percent=50.0)
    with pytest.raises(PlannerError) as exc:
        check_battery_config(config)
    assert exc.value.code == PlannerErrorCode.CONFIG_INVALID


def test_battery_config_valid():
    check_battery_config(_valid_config())


def test_battery_config_invalid_capacity():
    config = _valid_config(capacity_kwh=0.0)
    with pytest.raises(PlannerError) as exc:
        check_battery_config(config)
    assert exc.value.code == PlannerErrorCode.CONFIG_INVALID


def test_battery_config_invalid_charge_power():
    config = _valid_config(max_charge_w=0)
    with pytest.raises(PlannerError) as exc:
        check_battery_config(config)
    assert exc.value.code == PlannerErrorCode.CONFIG_INVALID


def test_battery_config_invalid_discharge_power():
    config = _valid_config(max_discharge_w=0)
    with pytest.raises(PlannerError) as exc:
        check_battery_config(config)
    assert exc.value.code == PlannerErrorCode.CONFIG_INVALID


# --- check_initial_soc ---

def test_initial_soc_out_of_range_negative():
    input_data = _valid_input()
    input_data["initial_state"]["battery_kwh"] = -1.0
    with pytest.raises(PlannerError) as exc:
        check_initial_soc(input_data, _valid_config())
    assert exc.value.code == PlannerErrorCode.INITIAL_SOC_OUT_OF_RANGE


def test_initial_soc_out_of_range_above_capacity():
    input_data = _valid_input()
    input_data["initial_state"]["battery_kwh"] = 999.0
    with pytest.raises(PlannerError) as exc:
        check_initial_soc(input_data, _valid_config())
    assert exc.value.code == PlannerErrorCode.INITIAL_SOC_OUT_OF_RANGE


def test_initial_soc_valid():
    check_initial_soc(_valid_input(initial_soc_kwh=5.0), _valid_config())


# --- check_soc_staleness ---

def test_soc_staleness_stale_logs_warning(caplog):
    stale_ts = _now() - timedelta(minutes=SOC_STALENESS_WARNING_MINUTES + 5)
    input_data = _valid_input()
    input_data["initial_state"]["soc_timestamp"] = stale_ts.isoformat()
    with caplog.at_level(logging.WARNING, logger="darkstar.planner.preflight"):
        check_soc_staleness(input_data)  # Must not raise
    assert "DATA_STALE" in caplog.text


def test_soc_staleness_fresh_no_warning(caplog):
    fresh_ts = _now() - timedelta(minutes=5)
    input_data = _valid_input()
    input_data["initial_state"]["soc_timestamp"] = fresh_ts.isoformat()
    with caplog.at_level(logging.WARNING, logger="darkstar.planner.preflight"):
        check_soc_staleness(input_data)
    assert "DATA_STALE" not in caplog.text


def test_soc_staleness_missing_timestamp_no_error():
    input_data = _valid_input()
    check_soc_staleness(input_data)  # No soc_timestamp → skip, no exception


# --- check_ev_chargers ---

def test_ev_chargers_missing_power():
    config = _valid_config()
    config["ev_chargers"] = [
        {"id": "ev1", "enabled": True, "rated_power_kw": 0.0, "battery_capacity_kwh": 60.0}
    ]
    with pytest.raises(PlannerError) as exc:
        check_ev_chargers(config)
    assert exc.value.code == PlannerErrorCode.EV_MISSING_POWER
    assert exc.value.details["charger_id"] == "ev1"


def test_ev_chargers_invalid_capacity():
    config = _valid_config()
    config["ev_chargers"] = [
        {"id": "ev1", "enabled": True, "rated_power_kw": 11.0, "battery_capacity_kwh": 0.0}
    ]
    with pytest.raises(PlannerError) as exc:
        check_ev_chargers(config)
    assert exc.value.code == PlannerErrorCode.EV_INVALID_CAPACITY


def test_ev_chargers_valid():
    config = _valid_config()
    config["ev_chargers"] = [
        {"id": "ev1", "enabled": True, "rated_power_kw": 11.0, "battery_capacity_kwh": 60.0}
    ]
    check_ev_chargers(config)


def test_ev_chargers_disabled_skipped():
    config = _valid_config()
    config["ev_chargers"] = [
        {"id": "ev1", "enabled": False, "rated_power_kw": 0.0, "battery_capacity_kwh": 0.0}
    ]
    check_ev_chargers(config)  # Disabled charger — no error


# --- check_ev_deadlines ---

def test_ev_deadlines_past_logs_warning(caplog):
    config = _valid_config()
    past_deadline = (_now() - timedelta(hours=1)).isoformat()
    config["ev_chargers"] = [
        {"id": "ev1", "enabled": True, "rated_power_kw": 11.0, "battery_capacity_kwh": 60.0, "deadline": past_deadline}
    ]
    with caplog.at_level(logging.WARNING, logger="darkstar.planner.preflight"):
        check_ev_deadlines(config, _now())
    assert "EV_DEADLINE_PAST" in caplog.text


def test_ev_deadlines_future_no_warning(caplog):
    config = _valid_config()
    future_deadline = (_now() + timedelta(hours=5)).isoformat()
    config["ev_chargers"] = [
        {"id": "ev1", "enabled": True, "rated_power_kw": 11.0, "battery_capacity_kwh": 60.0, "deadline": future_deadline}
    ]
    with caplog.at_level(logging.WARNING, logger="darkstar.planner.preflight"):
        check_ev_deadlines(config, _now())
    assert "EV_DEADLINE_PAST" not in caplog.text


# --- check_price_data ---

def test_price_data_empty():
    input_data = _valid_input()
    input_data["price_data"] = []
    with pytest.raises(PlannerError) as exc:
        check_price_data(input_data, _now())
    assert exc.value.code == PlannerErrorCode.PRICES_UNAVAILABLE


def test_price_data_insufficient_horizon():
    now = _now()
    input_data = _valid_input()
    # Only 1 hour of future prices
    input_data["price_data"] = [_price_slot(now)]
    with pytest.raises(PlannerError) as exc:
        check_price_data(input_data, now)
    assert exc.value.code == PlannerErrorCode.PRICES_UNAVAILABLE


def test_price_data_sufficient():
    now = _now()
    prices = [_price_slot(now + timedelta(hours=i)) for i in range(6)]
    input_data = {"price_data": prices, "forecast_data": [], "initial_state": {}}
    check_price_data(input_data, now)


# --- check_forecast_data ---

def test_forecast_data_empty():
    input_data = _valid_input()
    input_data["forecast_data"] = []
    with pytest.raises(PlannerError) as exc:
        check_forecast_data(input_data)
    assert exc.value.code == PlannerErrorCode.FORECAST_UNAVAILABLE


def test_forecast_data_valid():
    check_forecast_data(_valid_input())


def test_forecast_data_doesnt_cover_price_horizon():
    now = _now()
    input_data = {
        "price_data": [_price_slot(now + timedelta(hours=i)) for i in range(12)],
        "forecast_data": [_forecast_slot(now + timedelta(hours=i)) for i in range(2)],
        "initial_state": {},
    }
    with pytest.raises(PlannerError) as exc:
        check_forecast_data(input_data)
    assert exc.value.code == PlannerErrorCode.FORECAST_UNAVAILABLE


# --- check_numeric_sanity ---

def test_numeric_sanity_nan_in_price():
    input_data = _valid_input()
    input_data["price_data"][0]["import_price_sek_kwh"] = math.nan
    with pytest.raises(PlannerError) as exc:
        check_numeric_sanity(input_data)
    assert exc.value.code == PlannerErrorCode.NUMERIC_INVALID


def test_numeric_sanity_inf_in_forecast():
    input_data = _valid_input()
    input_data["forecast_data"][0]["pv_forecast_kwh"] = math.inf
    with pytest.raises(PlannerError) as exc:
        check_numeric_sanity(input_data)
    assert exc.value.code == PlannerErrorCode.NUMERIC_INVALID


def test_numeric_sanity_valid():
    check_numeric_sanity(_valid_input())


# --- run_preflight integration ---

def test_run_preflight_blocking_check_halts():
    """A blocking failure stops execution (no further checks run)."""
    config = _valid_config(min_soc_percent=90.0, max_soc_percent=10.0)  # Invalid range
    with pytest.raises(PlannerError) as exc:
        run_preflight(_valid_input(), config)
    assert exc.value.code == PlannerErrorCode.CONFIG_INVALID


def test_run_preflight_warning_only_does_not_raise(caplog):
    """Warning-only conditions (stale SoC, past EV deadline) do not raise."""
    config = _valid_config()
    stale_ts = (_now() - timedelta(minutes=SOC_STALENESS_WARNING_MINUTES + 10)).isoformat()
    input_data = _valid_input()
    input_data["initial_state"]["soc_timestamp"] = stale_ts
    with caplog.at_level(logging.WARNING, logger="darkstar.planner.preflight"):
        run_preflight(input_data, config)  # Must not raise
    assert "DATA_STALE" in caplog.text
