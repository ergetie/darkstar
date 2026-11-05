"""Unit tests for planner/strategy/manual_plan.py charge power resolution."""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from planner.strategy.manual_plan import apply_manual_plan

TZ = "Europe/Stockholm"


def _df() -> pd.DataFrame:
    index = pd.date_range("2026-01-15 10:00", periods=4, freq="15min", tz=TZ)
    return pd.DataFrame({"charge_kw": 0.0}, index=index)


def _plan() -> list[dict]:
    return [
        {
            "id": "charge-1",
            "content": "Charge",
            "start": "2026-01-15T10:00:00",
            "end": "2026-01-15T11:00:00",
        }
    ]


def _config(unit: str, battery: dict) -> dict:
    return {"timezone": TZ, "executor": {"inverter": {"control_unit": unit}}, "battery": battery}


def test_amps_config_without_stray_key_plans_resolved_kw():
    config = _config("A", {"max_charge_a": 100, "nominal_voltage_v": 48})
    result = apply_manual_plan(_df(), _plan(), config)
    assert result["charge_kw"].tolist() == pytest.approx([4.8] * 4)
    assert (result["manual_action"] == "Charge").all()


def test_watts_config_plans_resolved_kw():
    config = _config("W", {"max_charge_w": 5000})
    result = apply_manual_plan(_df(), _plan(), config)
    assert result["charge_kw"].tolist() == [5.0] * 4


def test_stray_kw_key_is_ignored():
    config = _config("W", {"max_charge_w": 5000, "max_charge_power_kw": 8})
    result = apply_manual_plan(_df(), _plan(), config)
    assert result["charge_kw"].tolist() == [5.0] * 4


def test_unconfigured_limit_plans_zero_and_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="darkstar.planner.manual_plan"):
        result = apply_manual_plan(_df(), _plan(), _config("A", {}))
    assert result["charge_kw"].tolist() == [0.0] * 4
    assert "not configured" in caplog.text
