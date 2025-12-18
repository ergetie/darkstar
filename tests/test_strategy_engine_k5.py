import pytest
from backend.strategy.engine import StrategyEngine


def test_high_volatility():
    engine = StrategyEngine(config={})

    # Spread = 2.0 - 0.1 = 1.9 (> 1.5)
    prices = [{"value": 0.1}, {"value": 2.0}]
    input_data = {"prices": prices, "context": {}}

    overrides = engine.decide(input_data)

    assert "kepler" in overrides
    assert overrides["kepler"]["wear_cost_sek_per_kwh"] == 0.0
    assert overrides["kepler"]["ramping_cost_sek_per_kw"] == 0.01
    assert overrides["kepler"]["export_threshold_sek_per_kwh"] == 0.05


def test_low_volatility():
    engine = StrategyEngine(config={})

    # Spread = 0.4 - 0.1 = 0.3 (< 0.5)
    prices = [{"value": 0.1}, {"value": 0.4}]
    input_data = {"prices": prices, "context": {}}

    overrides = engine.decide(input_data)

    assert "kepler" in overrides
    assert overrides["kepler"]["wear_cost_sek_per_kwh"] == 1.0
    assert overrides["kepler"]["ramping_cost_sek_per_kw"] == 0.5
    assert overrides["kepler"]["export_threshold_sek_per_kwh"] == 0.2


def test_normal_volatility():
    engine = StrategyEngine(config={})

    # Spread = 1.0 - 0.1 = 0.9 (Normal)
    prices = [{"value": 0.1}, {"value": 1.0}]
    input_data = {"prices": prices, "context": {}}

    overrides = engine.decide(input_data)

    assert "kepler" not in overrides
