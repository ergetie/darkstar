from backend.strategy.engine import RISK_BASELINE_SHIFTS, StrategyEngine


def test_high_volatility():
    """High volatility (spread=1.9) with default risk=3: expect reduced threshold"""
    engine = StrategyEngine(config={})

    # Spread = 2.0 - 0.1 = 1.9 (> 1.5)
    prices = [{"value": 0.1}, {"value": 2.0}]
    input_data = {"prices": prices, "context": {}}

    overrides = engine.decide(input_data)

    assert "kepler" in overrides
    assert overrides["kepler"]["wear_cost_sek_per_kwh"] == 0.0
    assert overrides["kepler"]["ramping_cost_sek_per_kw"] == 0.01
    # With risk=3 (baseline=0.05) and spread_norm=(1.9-0.3)/1.7=0.941:
    # threshold = 0.50 - (0.50-0.05)*0.941 ≈ 0.076
    assert overrides["kepler"]["export_threshold_sek_per_kwh"] == 0.076


def test_low_volatility():
    """Low volatility (spread=0.3) with default risk=3: expect max threshold"""
    engine = StrategyEngine(config={})

    # Spread = 0.4 - 0.1 = 0.3 (< 0.5)
    prices = [{"value": 0.1}, {"value": 0.4}]
    input_data = {"prices": prices, "context": {}}

    overrides = engine.decide(input_data)

    assert "kepler" in overrides
    assert overrides["kepler"]["wear_cost_sek_per_kwh"] == 1.0
    assert overrides["kepler"]["ramping_cost_sek_per_kw"] == 0.5
    # With spread_norm=0.0 (clamped), threshold should be 0.50
    assert overrides["kepler"]["export_threshold_sek_per_kwh"] == 0.5


def test_medium_volatility():
    """Medium volatility (spread=0.9) with default risk=3: expect continuous scaling"""
    engine = StrategyEngine(config={})

    # Spread = 1.0 - 0.1 = 0.9 (between 0.5 and 1.5)
    prices = [{"value": 0.1}, {"value": 1.0}]
    input_data = {"prices": prices, "context": {}}

    overrides = engine.decide(input_data)

    assert "kepler" in overrides
    # spread_norm = (0.9-0.3)/1.7 = 0.353
    # threshold = 0.50 - (0.50-0.05)*0.353 ≈ 0.341
    assert overrides["kepler"]["export_threshold_sek_per_kwh"] == 0.341
    # Wear/ramping should be interpolated for medium volatility
    assert "wear_cost_sek_per_kwh" in overrides["kepler"]
    assert "ramping_cost_sek_per_kw" in overrides["kepler"]


# Dynamic Export Threshold Tests


def test_spread_02_risk3_threshold_05():
    """spread=0.2, risk=3 → threshold = 0.50 (clamped to max)"""
    engine = StrategyEngine(config={"s_index": {"risk_appetite": 3}})
    prices = [{"value": 0.5}, {"value": 0.7}]  # spread = 0.2
    input_data = {"prices": prices, "context": {}}

    overrides = engine.decide(input_data)

    assert overrides["kepler"]["export_threshold_sek_per_kwh"] == 0.5


def test_spread_25_risk5_threshold_00():
    """spread=2.5, risk=5 → threshold = 0.00 (clamped to min)"""
    engine = StrategyEngine(config={"s_index": {"risk_appetite": 5}})
    prices = [{"value": 0.5}, {"value": 3.0}]  # spread = 2.5
    input_data = {"prices": prices, "context": {}}

    overrides = engine.decide(input_data)

    assert overrides["kepler"]["export_threshold_sek_per_kwh"] == 0.0


def test_spread_10_risk3_threshold_024():
    """spread=1.0, risk=3 → threshold ≈ 0.24"""
    engine = StrategyEngine(config={"s_index": {"risk_appetite": 3}})
    prices = [{"value": 0.5}, {"value": 1.5}]  # spread = 1.0
    input_data = {"prices": prices, "context": {}}

    overrides = engine.decide(input_data)

    # spread_norm = (1.0 - 0.3) / 1.7 = 0.412
    # baseline for risk=3 = 0.05
    # threshold = 0.50 - (0.50 - 0.05) * 0.412 = 0.315 ≈ 0.315
    assert overrides["kepler"]["export_threshold_sek_per_kwh"] == 0.315


def test_spread_05_risk3_threshold_038():
    """spread=0.5, risk=3 → threshold ≈ 0.38 (previously would have been 0.0 in the gap)"""
    engine = StrategyEngine(config={"s_index": {"risk_appetite": 3}})
    prices = [{"value": 0.5}, {"value": 1.0}]  # spread = 0.5
    input_data = {"prices": prices, "context": {}}

    overrides = engine.decide(input_data)

    # spread_norm = (0.5 - 0.3) / 1.7 = 0.118
    # baseline for risk=3 = 0.05
    # threshold = 0.50 - (0.50 - 0.05) * 0.118 = 0.447 ≈ 0.447
    assert overrides["kepler"]["export_threshold_sek_per_kwh"] == 0.447


def test_risk_appetite_affects_floor_not_ceiling():
    """Risk appetite should shift the floor (minimum threshold) not the ceiling"""
    # Low volatility test - should have same ceiling regardless of risk
    prices_low = [{"value": 0.1}, {"value": 0.35}]  # spread = 0.25
    input_data_low = {"prices": prices_low, "context": {}}

    for risk in [1, 3, 5]:
        engine = StrategyEngine(config={"s_index": {"risk_appetite": risk}})
        overrides = engine.decide(input_data_low)
        # All should have max threshold at low spread
        assert overrides["kepler"]["export_threshold_sek_per_kwh"] == 0.5

    # High volatility test - should have different floors based on risk
    prices_high = [{"value": 0.5}, {"value": 3.0}]  # spread = 2.5
    input_data_high = {"prices": prices_high, "context": {}}

    thresholds = {}
    for risk in [1, 2, 3, 4, 5]:
        engine = StrategyEngine(config={"s_index": {"risk_appetite": risk}})
        overrides = engine.decide(input_data_high)
        thresholds[risk] = overrides["kepler"]["export_threshold_sek_per_kwh"]

    # Lower risk (more conservative) should have higher minimum threshold
    assert thresholds[1] > thresholds[3] > thresholds[5]
    # Verify exact values
    assert thresholds[1] == 0.15  # Conservative
    assert thresholds[5] == 0.0  # Aggressive


def test_wear_and_ramping_costs_still_present_high_spread():
    """Ensure wear_cost_sek_per_kwh and ramping_cost_sek_per_kw overrides are present for high spread"""
    engine = StrategyEngine(config={})
    prices = [{"value": 0.1}, {"value": 2.0}]  # spread = 1.9 (high)
    input_data = {"prices": prices, "context": {}}

    overrides = engine.decide(input_data)

    assert "wear_cost_sek_per_kwh" in overrides["kepler"]
    assert "ramping_cost_sek_per_kw" in overrides["kepler"]
    assert overrides["kepler"]["wear_cost_sek_per_kwh"] == 0.0
    assert overrides["kepler"]["ramping_cost_sek_per_kw"] == 0.01


def test_wear_and_ramping_costs_still_present_low_spread():
    """Ensure wear_cost_sek_per_kwh and ramping_cost_sek_per_kw overrides are present for low spread"""
    engine = StrategyEngine(config={})
    prices = [{"value": 0.1}, {"value": 0.4}]  # spread = 0.3 (low)
    input_data = {"prices": prices, "context": {}}

    overrides = engine.decide(input_data)

    assert "wear_cost_sek_per_kwh" in overrides["kepler"]
    assert "ramping_cost_sek_per_kw" in overrides["kepler"]
    assert overrides["kepler"]["wear_cost_sek_per_kwh"] == 1.0
    assert overrides["kepler"]["ramping_cost_sek_per_kw"] == 0.5


def test_risk_baseline_shifts_mapping():
    """Verify the RISK_BASELINE_SHIFTS mapping is correct"""
    assert RISK_BASELINE_SHIFTS[1] == 0.15
    assert RISK_BASELINE_SHIFTS[2] == 0.10
    assert RISK_BASELINE_SHIFTS[3] == 0.05
    assert RISK_BASELINE_SHIFTS[4] == 0.02
    assert RISK_BASELINE_SHIFTS[5] == 0.00


def test_default_risk_appetite_is_3():
    """When no risk_appetite specified, should default to 3"""
    engine = StrategyEngine(config={})
    prices = [{"value": 0.5}, {"value": 2.5}]  # spread = 2.0
    input_data = {"prices": prices, "context": {}}

    overrides = engine.decide(input_data)

    # With risk=3 (baseline=0.05) and spread_norm=(2.0-0.3)/1.7=1.0:
    # threshold = 0.50 - (0.50-0.05)*1.0 = 0.05
    assert overrides["kepler"]["export_threshold_sek_per_kwh"] == 0.05


def test_continuous_threshold_scaling():
    """Test that threshold scales continuously across spread values"""
    engine = StrategyEngine(config={"s_index": {"risk_appetite": 3}})

    spreads_and_expected = [
        (0.0, 0.5),  # Clamped low
        (0.2, 0.5),  # Clamped low
        (0.3, 0.5),  # Minimum spread_norm
        (0.5, 0.447),  # Gap scenario (previously 0.0!)
        (1.0, 0.315),  # Middle
        (1.5, 0.182),  # Upper middle
        (2.0, 0.05),  # Maximum spread_norm
        (2.5, 0.05),  # Clamped high
    ]

    for spread, expected in spreads_and_expected:
        prices = [{"value": 0.5}, {"value": 0.5 + spread}]
        input_data = {"prices": prices, "context": {}}
        overrides = engine.decide(input_data)
        assert overrides["kepler"]["export_threshold_sek_per_kwh"] == expected, (
            f"Failed for spread={spread}"
        )


def test_volatility_event_message_uses_configured_currency(monkeypatch):
    events = []
    monkeypatch.setattr(
        "backend.strategy.engine.append_strategy_event",
        lambda kind, message, data: events.append(message),
    )
    engine = StrategyEngine(config={"nordpool": {"currency": "EUR"}})
    engine.decide({"prices": [{"value": 0.1}, {"value": 2.0}], "context": {}})

    assert events == ["High Price Spread (1.90 EUR). Aggressive Mode engaged."]
