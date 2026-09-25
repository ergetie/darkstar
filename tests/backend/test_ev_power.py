"""Shared EV charger power model (ev-planning-model: ev-charging-power)."""

from __future__ import annotations

import pytest

from backend.core.ev_power import charger_max_kw, charger_power_limits, nominal_voltage_v


def test_10a_three_phase_current_charger():
    cfg = {"type": "current", "min_current_a": 6, "max_current_a": 10, "phases": [1, 2, 3]}
    min_kw, max_kw = charger_power_limits(cfg, 230.0)
    assert max_kw == pytest.approx(6.9)
    assert min_kw == pytest.approx(6 * 3 * 230 / 1000 * 1.01)
    assert min_kw == pytest.approx(4.18, abs=0.01)


def test_prod_12a_three_phase_is_about_8_3_kw():
    cfg = {"type": "current", "max_current_a": 12, "phases": [1, 2, 3]}
    assert charger_max_kw(cfg, 230.0) == pytest.approx(8.28)


def test_single_phase_and_voltage_scale():
    cfg = {"type": "current", "min_current_a": 6, "max_current_a": 16, "phases": [2]}
    assert charger_max_kw(cfg, 240.0) == pytest.approx(16 * 240 / 1000)


def test_min_current_defaults_to_6():
    cfg = {"type": "current", "max_current_a": 16, "phases": [1, 2, 3]}
    assert charger_power_limits(cfg, 230.0)[0] == pytest.approx(6 * 3 * 230 / 1000 * 1.01)


def test_min_never_exceeds_max():
    cfg = {"type": "current", "min_current_a": 6, "max_current_a": 6, "phases": [1, 2, 3]}
    min_kw, max_kw = charger_power_limits(cfg, 230.0)
    assert min_kw == max_kw == pytest.approx(4.14)


def test_binary_charger_uses_rated_power():
    assert charger_power_limits({"type": "binary", "rated_power_kw": 3.7}, 230.0) == (3.7, 3.7)
    # Untyped entries default to binary.
    assert charger_power_limits({"rated_power_kw": 7.4}, 230.0) == (7.4, 7.4)


@pytest.mark.parametrize(
    "cfg",
    [
        {"type": "current", "phases": [1, 2, 3]},  # missing max_current_a
        {"type": "current", "max_current_a": 16},  # missing phases
        {"type": "current", "max_current_a": 0, "phases": [1, 2, 3]},
        {"type": "current", "max_current_a": 16, "phases": []},
        {"type": "binary"},  # missing rated_power_kw
        {"type": "binary", "rated_power_kw": 0},
        {"type": "binary", "rated_power_kw": "abc"},
        # Legacy keys are never read.
        {"type": "binary", "max_power_kw": 11.0, "nominal_power_kw": 11.0},
        {"type": "current", "max_power_kw": 11.0},
    ],
)
def test_invalid_config_yields_zero(cfg):
    assert charger_power_limits(cfg, 230.0) == (0.0, 0.0)


def _grid(v):
    return {"system": {"grid": {"nominal_voltage_v": v}}}


def test_nominal_voltage_default_and_override():
    assert nominal_voltage_v({}) == 230.0
    assert nominal_voltage_v(None) == 230.0
    assert nominal_voltage_v({"system": {"grid": {}}}) == 230.0
    assert nominal_voltage_v(_grid(240)) == 240.0
    assert nominal_voltage_v(_grid(0)) == 230.0
    assert nominal_voltage_v(_grid("x")) == 230.0


def test_nominal_voltage_ignores_legacy_load_balancing_key():
    """system.grid.nominal_voltage_v is the single source; the migrated-away key is not read."""
    assert nominal_voltage_v({"load_balancing": {"nominal_voltage_v": 220}}) == 230.0


def test_binary_charger_ignores_voltage():
    """Binary chargers use rated_power_kw only: no voltage/amps/phases involved."""
    cfg = {"type": "binary", "rated_power_kw": 3.7, "max_current_a": 32, "phases": [1, 2, 3]}
    for voltage in (120.0, 230.0, 240.0):
        assert charger_power_limits(cfg, voltage) == (3.7, 3.7)
