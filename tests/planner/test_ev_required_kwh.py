"""Unit tests for planner.pipeline._calculate_required_kwh (double-count fix).

A live SoC reading already reflects charging progress, so delivered-today
must NOT be subtracted on top of it. The delivered-today fallback exists only
for SoC-less chargers, and only when exactly one charger is enabled (the
slot_observations.ev_charging_kwh column is an unattributable aggregate).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import pytz

from planner.pipeline import _calculate_required_kwh

TZ = pytz.timezone("Europe/Stockholm")


def test_live_soc_does_not_double_count_delivered_today():
    """Regression case: SoC=65%, target=80%, capacity=100kWh -> required=15kWh,
    even though 15 kWh was already delivered today (that's what got it to 65%)."""
    charger_cfg = {"id": "ev1", "target_soc_percent": 80, "battery_capacity_kwh": 100.0}
    ha_state = {"soc_percent": 65.0}

    with patch("planner.pipeline._ev_delivered_today_kwh", return_value=15.0) as mock_delivered:
        required = _calculate_required_kwh(charger_cfg, ha_state, "some.db", TZ)

    assert required == pytest.approx(15.0)
    mock_delivered.assert_not_called()


def test_live_soc_zero_is_not_treated_as_unavailable():
    """A real 0.0% reading is a value, not 'unavailable' — must not trigger
    the delivered-today fallback path."""
    charger_cfg = {"id": "ev1", "target_soc_percent": 50, "battery_capacity_kwh": 40.0}
    ha_state = {"soc_percent": 0.0}

    with patch("planner.pipeline._ev_delivered_today_kwh", return_value=5.0) as mock_delivered:
        required = _calculate_required_kwh(charger_cfg, ha_state, "some.db", TZ)

    assert required == pytest.approx(20.0)  # (50-0)/100*40
    mock_delivered.assert_not_called()


def test_soc_unavailable_single_charger_subtracts_delivered():
    charger_cfg = {"id": "ev1", "target_soc_percent": 80, "battery_capacity_kwh": 60.0}
    ha_state = {"soc_percent": None}

    with patch("planner.pipeline._ev_delivered_today_kwh", return_value=10.0):
        required = _calculate_required_kwh(
            charger_cfg, ha_state, "some.db", TZ, single_enabled_charger=True
        )

    # target/100*capacity - delivered = 0.8*60 - 10 = 38
    assert required == pytest.approx(38.0)


def test_soc_unavailable_multi_charger_warns_and_does_not_subtract(caplog):
    charger_cfg = {"id": "ev1", "target_soc_percent": 80, "battery_capacity_kwh": 60.0}
    ha_state = {"soc_percent": None}

    with (
        patch("planner.pipeline._ev_delivered_today_kwh", return_value=10.0) as mock_delivered,
        caplog.at_level("WARNING"),
    ):
        required = _calculate_required_kwh(
            charger_cfg, ha_state, "some.db", TZ, single_enabled_charger=False
        )

    assert required == pytest.approx(48.0)  # 0.8*60, no subtraction
    mock_delivered.assert_not_called()
    assert any("unattributable" in r.getMessage() for r in caplog.records)


def test_soc_unavailable_no_db_path_no_subtraction():
    charger_cfg = {"id": "ev1", "target_soc_percent": 80, "battery_capacity_kwh": 60.0}
    ha_state = {"soc_percent": None}

    required = _calculate_required_kwh(charger_cfg, ha_state, None, TZ)
    assert required == pytest.approx(48.0)


def test_soc_missing_key_treated_as_unavailable():
    """No 'soc_percent' key at all (e.g. no matching HA state found) behaves
    the same as an explicit None — falls back, doesn't crash."""
    charger_cfg = {"id": "ev1", "target_soc_percent": 80, "battery_capacity_kwh": 60.0}
    ha_state: dict = {}

    with patch("planner.pipeline._ev_delivered_today_kwh", return_value=0.0):
        required = _calculate_required_kwh(charger_cfg, ha_state, "some.db", TZ)

    assert required == pytest.approx(48.0)
