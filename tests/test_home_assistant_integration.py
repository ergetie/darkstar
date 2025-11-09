"""
Tests covering Home Assistant integrations and dynamic S-index behaviour.
"""

from __future__ import annotations

import importlib
import sqlite3
from datetime import datetime

import pandas as pd
import pytest
import pytz

import inputs
import planner as planner_module


class DummyResponse:
    """Simple mock response for requests.get."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return

    def json(self):
        return self._payload


def test_get_initial_state_prefers_home_assistant(monkeypatch, tmp_path):
    """Ensure Home Assistant SoC overrides defaults when available."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("battery:\n  capacity_kwh: 10.0\n", encoding="utf-8")

    monkeypatch.setattr(
        inputs,
        "load_home_assistant_config",
        lambda: {
            "url": "http://ha.local:8123",
            "token": "abc",
            "battery_soc_entity_id": "sensor.inverter_battery",
        },
    )

    def fake_get(url, headers, timeout):
        assert url.endswith("/api/states/sensor.inverter_battery")
        return DummyResponse({"state": "62.7"})

    monkeypatch.setattr(inputs.requests, "get", fake_get)

    state = inputs.get_initial_state(config_path=str(config_path))

    assert pytest.approx(state["battery_soc_percent"], rel=0.001) == 62.7
    assert pytest.approx(state["battery_kwh"], rel=0.001) == 6.27


def _load_webapp():
    """Import webapp lazily so tests skip if Flask is unavailable."""
    pytest.importorskip("flask", reason="Flask is required for webapp endpoint tests")
    return importlib.import_module("webapp")


def test_water_today_endpoint_ha(monkeypatch):
    """Water endpoint should prefer Home Assistant sensor when available."""
    webapp = _load_webapp()
    monkeypatch.setattr(
        webapp,
        "load_home_assistant_config",
        lambda: {"water_heater_daily_entity_id": "sensor.vvb_energy_daily"},
    )
    monkeypatch.setattr(webapp, "get_home_assistant_sensor_float", lambda entity_id: 4.56)
    monkeypatch.setattr(
        webapp.yaml,
        "safe_load",
        lambda _: {
            "learning": {"sqlite_path": "ignored.db"},
            "timezone": "Europe/Stockholm",
        },
    )

    client = webapp.app.test_client()
    resp = client.get("/api/ha/water_today")
    data = resp.get_json()

    assert resp.status_code == 200
    assert data["source"] == "home_assistant"
    assert pytest.approx(data["water_kwh_today"], rel=0.001) == 4.56


def test_water_today_endpoint_sqlite_fallback(monkeypatch, tmp_path):
    """Endpoint should fall back to sqlite tracker when HA sensor unavailable."""
    webapp = _load_webapp()
    sqlite_path = tmp_path / "planner_learning.db"
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    tz = pytz.timezone("Europe/Stockholm")

    with sqlite3.connect(sqlite_path) as conn:
        conn.execute(
            "CREATE TABLE daily_water (date TEXT PRIMARY KEY, used_kwh REAL, updated_at TEXT)"
        )
        today_key = datetime.now(tz).date().isoformat()
        conn.execute(
            "INSERT INTO daily_water (date, used_kwh, updated_at) VALUES (?, ?, ?)",
            (today_key, 7.25, datetime.now(tz).isoformat()),
        )
        conn.commit()

    monkeypatch.setattr(webapp, "load_home_assistant_config", lambda: {})
    monkeypatch.setattr(webapp, "get_home_assistant_sensor_float", lambda entity_id: None)
    monkeypatch.setattr(
        webapp.yaml,
        "safe_load",
        lambda _: {
            "learning": {"sqlite_path": str(sqlite_path)},
            "timezone": "Europe/Stockholm",
        },
    )

    client = webapp.app.test_client()
    resp = client.get("/api/ha/water_today")
    data = resp.get_json()

    assert resp.status_code == 200
    assert data["source"] == "sqlite"
    assert pytest.approx(data["water_kwh_today"], rel=0.001) == 7.25


def test_calculate_dynamic_s_index(monkeypatch):
    """Dynamic S-index should grow with PV deficit and colder forecasts."""
    planner_instance = planner_module.HeliosPlanner.__new__(planner_module.HeliosPlanner)
    planner_instance.config = {
        "s_index": {
            "mode": "dynamic",
            "static_factor": 1.05,
            "base_factor": 1.05,
            "max_factor": 1.50,
            "pv_deficit_weight": 0.30,
            "temp_weight": 0.20,
            "temp_baseline_c": 20.0,
            "temp_cold_c": -15.0,
            "days_ahead_for_sindex": [2, 3, 4],
        }
    }
    planner_instance.timezone = "Europe/Stockholm"
    planner_instance.daily_pv_forecast = {}
    planner_instance.daily_load_forecast = {}
    planner_instance._last_temperature_forecast = {}
    planner_instance.forecast_meta = {}

    # Avoid real API calls
    def fake_temperature_forecast(days, tz):
        return {offset: temp for offset, temp in zip(days, [5.0, 0.0, -10.0])}

    monkeypatch.setattr(planner_instance, "_fetch_temperature_forecast", fake_temperature_forecast)

    tz = pytz.timezone("Europe/Stockholm")
    base_date = datetime(2025, 6, 1, tzinfo=tz)
    dates = pd.date_range(base_date + pd.Timedelta(days=2), periods=96 * 3, freq="15min", tz=tz)
    df = pd.DataFrame(
        {
            "adjusted_load_kwh": [1.0] * len(dates),
            "adjusted_pv_kwh": [0.2] * len(dates),
        },
        index=dates,
    )

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            base = datetime(2025, 6, 1, 0, 0, 0)
            if tz:
                try:
                    return tz.localize(base)
                except AttributeError:
                    return base.replace(tzinfo=tz)
            return base

    monkeypatch.setattr(planner_module, "datetime", FixedDateTime)

    factor, debug = planner_instance._calculate_dynamic_s_index(
        df, planner_instance.config["s_index"], 1.50
    )

    assert factor is not None
    assert factor > planner_instance.config["s_index"]["base_factor"]
    assert debug["mode"] == "dynamic"
    assert debug["avg_deficit"] > 0
    assert debug["temp_adjustment"] > 0
