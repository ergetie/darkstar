"""Effective battery efficiency resolution, composition and config application."""

import copy
import math
import random
from datetime import datetime, timedelta

import pytest

from backend.learning import learned_parameters as lp
from backend.learning.battery_estimators import (
    KEY_CHARGE_LOSS,
    KEY_DISCHARGE_EFFICIENCY,
    KEY_RTE,
    KEY_STANDBY_W,
)
from tests.learning.battery_synth import TZ

NOW = TZ.localize(datetime(2026, 3, 10, 1, 0))
SYSTEM_CONFIG = {
    "system": {
        "battery": {"capacity_kwh": 30.0, "charge_efficiency": 0.92, "discharge_efficiency": 0.95}
    }
}
TOP_LEVEL_CONFIG = {
    "battery": {"capacity_kwh": 30.0, "charge_efficiency": 0.92, "discharge_efficiency": 0.95}
}


def _learned(key: str, value: float, age_days: float = 1.0, **kwargs) -> lp.ParameterState:
    return lp.ParameterState(
        key=key,
        learned_value=value,
        applied_value=value,
        confidence=0.9,
        estimated_at=NOW - timedelta(days=age_days),
        applied_at=NOW - timedelta(days=age_days),
        **kwargs,
    )


def _states(rte=0.962, loss=0.075, age=1.0, **extra) -> dict[str, lp.ParameterState]:
    states = {
        KEY_RTE: _learned(KEY_RTE, rte, age),
        KEY_CHARGE_LOSS: _learned(KEY_CHARGE_LOSS, loss, age),
    }
    states.update(extra)
    return states


def test_composition_matches_the_design_numbers() -> None:
    resolved = lp.resolve_battery_parameters(SYSTEM_CONFIG, _states(), NOW)

    assert resolved.learned
    assert resolved.charge_efficiency == pytest.approx(0.907, abs=0.001)
    assert resolved.discharge_efficiency == pytest.approx(0.951, abs=0.001)
    sources = {k: p.source for k, p in resolved.parameters.items()}
    assert sources == {
        KEY_RTE: "learned",
        KEY_CHARGE_LOSS: "learned",
        KEY_STANDBY_W: "config",
        KEY_DISCHARGE_EFFICIENCY: "default",
    }
    assert resolved.parameters[KEY_DISCHARGE_EFFICIENCY].value == 0.97


def test_partial_data_falls_back_for_both_efficiencies() -> None:
    states = {KEY_RTE: _learned(KEY_RTE, 0.962)}
    resolved = lp.resolve_battery_parameters(SYSTEM_CONFIG, states, NOW)

    assert not resolved.learned
    assert (resolved.charge_efficiency, resolved.discharge_efficiency) == (0.92, 0.95)
    assert resolved.missing == [KEY_CHARGE_LOSS]


def test_fresh_install_reports_fallback_sources_and_no_learned_value() -> None:
    resolved = lp.resolve_battery_parameters(SYSTEM_CONFIG, {}, NOW)

    assert not resolved.learned
    assert resolved.missing == [KEY_RTE, KEY_CHARGE_LOSS]
    for key in (KEY_RTE, KEY_CHARGE_LOSS, KEY_STANDBY_W):
        assert resolved.parameters[key].source == "config"
        assert resolved.parameters[key].learned_value is None


def test_config_defaults_apply_when_keys_are_absent() -> None:
    resolved = lp.resolve_battery_parameters({}, {}, NOW)
    assert (resolved.charge_efficiency, resolved.discharge_efficiency) == (0.95, 0.95)


def test_expiry_after_31_days_and_validity_at_30() -> None:
    fresh = lp.resolve_battery_parameters(SYSTEM_CONFIG, _states(age=30), NOW)
    assert fresh.learned and fresh.parameters[KEY_RTE].source == "learned"

    expired = lp.resolve_battery_parameters(SYSTEM_CONFIG, _states(age=31), NOW)
    assert not expired.learned
    assert expired.parameters[KEY_RTE].source == "expired"
    assert expired.parameters[KEY_RTE].value is None
    assert (expired.charge_efficiency, expired.discharge_efficiency) == (0.92, 0.95)
    assert expired.parameters[KEY_RTE].expires_at == NOW - timedelta(days=1)


def test_locked_value_is_used_beyond_30_days() -> None:
    states = _states(age=90)
    states[KEY_RTE] = _learned(KEY_RTE, 0.962, 90, locked=True, locked_value=0.95)
    states[KEY_CHARGE_LOSS] = _learned(KEY_CHARGE_LOSS, 0.075, 90, locked=True, locked_value=0.05)

    resolved = lp.resolve_battery_parameters(SYSTEM_CONFIG, states, NOW)

    assert resolved.learned
    assert resolved.parameters[KEY_RTE].source == "locked"
    assert resolved.parameters[KEY_RTE].value == 0.95
    assert resolved.charge_efficiency == pytest.approx((1 - 0.05) * math.sqrt(0.95))


def test_lock_of_discharge_efficiency_replaces_the_default() -> None:
    states = _states()
    states[KEY_DISCHARGE_EFFICIENCY] = lp.ParameterState(
        key=KEY_DISCHARGE_EFFICIENCY, locked=True, locked_value=0.95
    )
    resolved = lp.resolve_battery_parameters(SYSTEM_CONFIG, states, NOW)

    assert resolved.parameters[KEY_DISCHARGE_EFFICIENCY].source == "locked"
    assert resolved.discharge_efficiency == pytest.approx(math.sqrt(0.962) * 0.95)


def test_locked_rte_alone_still_needs_charge_loss() -> None:
    states = {KEY_RTE: lp.ParameterState(key=KEY_RTE, locked=True, locked_value=0.95)}
    resolved = lp.resolve_battery_parameters(SYSTEM_CONFIG, states, NOW)

    assert not resolved.learned
    assert resolved.missing == [KEY_CHARGE_LOSS]


def test_standby_never_changes_the_pair() -> None:
    plain = lp.resolve_battery_parameters(SYSTEM_CONFIG, _states(), NOW)
    with_standby = lp.resolve_battery_parameters(
        SYSTEM_CONFIG, _states() | {KEY_STANDBY_W: _learned(KEY_STANDBY_W, 80.0)}, NOW
    )
    assert with_standby.parameters[KEY_STANDBY_W].value == 80.0
    assert (with_standby.charge_efficiency, with_standby.discharge_efficiency) == (
        plain.charge_efficiency,
        plain.discharge_efficiency,
    )
    assert lp.apply_to_config(SYSTEM_CONFIG, with_standby) == lp.apply_to_config(
        SYSTEM_CONFIG, plain
    )


@pytest.mark.parametrize(
    ("config", "section"),
    [(SYSTEM_CONFIG, ("system", "battery")), (TOP_LEVEL_CONFIG, ("battery",))],
)
def test_apply_to_config_replaces_keys_in_the_planner_layout(config, section) -> None:
    before = copy.deepcopy(config)
    resolved = lp.resolve_battery_parameters(config, _states(), NOW)

    applied = lp.apply_to_config(config, resolved)

    target = applied
    for part in section:
        target = target[part]
    assert target["charge_efficiency"] == resolved.charge_efficiency
    assert target["discharge_efficiency"] == resolved.discharge_efficiency
    assert target["capacity_kwh"] == 30.0
    assert config == before  # input not mutated


def test_apply_to_config_without_learned_pair_is_an_equal_copy() -> None:
    resolved = lp.resolve_battery_parameters(SYSTEM_CONFIG, {}, NOW)
    applied = lp.apply_to_config(SYSTEM_CONFIG, resolved)

    assert applied == SYSTEM_CONFIG and applied is not SYSTEM_CONFIG
    assert applied["system"]["battery"] is not SYSTEM_CONFIG["system"]["battery"]


def test_system_battery_wins_over_top_level_like_the_planner() -> None:
    config = {**TOP_LEVEL_CONFIG, **SYSTEM_CONFIG, "battery": {"charge_efficiency": 0.5}}
    resolved = lp.resolve_battery_parameters(config, _states(), NOW)
    applied = lp.apply_to_config(config, resolved)

    assert applied["system"]["battery"]["charge_efficiency"] == resolved.charge_efficiency
    assert applied["battery"]["charge_efficiency"] == 0.5


@pytest.mark.parametrize(
    ("key", "value", "ok"),
    [
        (KEY_DISCHARGE_EFFICIENCY, 0.85, True),
        (KEY_DISCHARGE_EFFICIENCY, 1.0, True),
        (KEY_DISCHARGE_EFFICIENCY, 0.84, False),
        (KEY_DISCHARGE_EFFICIENCY, 1.01, False),
        (KEY_RTE, 0.7, False),
        (KEY_CHARGE_LOSS, 0.2, False),
        (KEY_STANDBY_W, 301.0, False),
        (KEY_RTE, float("nan"), False),
    ],
)
def test_lock_value_validation(key: str, value: float, ok: bool) -> None:
    if ok:
        lp.validate_lock_value(key, value)
    else:
        with pytest.raises(ValueError, match=r"finite|between"):
            lp.validate_lock_value(key, value)


def test_ac_flows_through_composed_pair_reproduce_true_stored_energy() -> None:
    """Identity test: AC-side flows rolled with the composed pair match a DC battery."""
    true_rte, ell, eta = 0.96, 0.07, 0.97
    states = {
        KEY_RTE: _learned(KEY_RTE, true_rte),
        KEY_CHARGE_LOSS: _learned(KEY_CHARGE_LOSS, ell),
        KEY_DISCHARGE_EFFICIENCY: lp.ParameterState(
            key=KEY_DISCHARGE_EFFICIENCY, locked=True, locked_value=eta
        ),
    }
    resolved = lp.resolve_battery_parameters(SYSTEM_CONFIG, states, NOW)
    rng = random.Random(3)
    true_stored = kepler_stored = 10.0
    root = math.sqrt(true_rte)
    for _ in range(500):
        ac_charge = rng.uniform(0.0, 1.5) if rng.random() < 0.5 else 0.0
        dc_discharge = rng.uniform(0.0, 1.0) if ac_charge == 0.0 else 0.0
        ac_discharge = dc_discharge * eta
        dc_charge = ac_charge * (1.0 - ell)
        true_stored += dc_charge * root - dc_discharge / root
        kepler_stored += (
            ac_charge * resolved.charge_efficiency - ac_discharge / resolved.discharge_efficiency
        )
    assert kepler_stored == pytest.approx(true_stored, rel=1e-9)

    # The AC-side pair applied to DC counters (the mixing the design forbids) is wrong.
    assert resolved.charge_efficiency != pytest.approx(math.sqrt(true_rte), abs=0.02)
