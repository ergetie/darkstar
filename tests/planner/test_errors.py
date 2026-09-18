"""Tests for planner/errors.py"""

import pytest

from planner.errors import (
    PlannerError,
    PlannerErrorCode,
    fix_hints,
    is_config_blocking,
    is_transient,
    is_warning_only,
    user_message,
)


def test_every_code_has_nonempty_user_message():
    for code in PlannerErrorCode:
        msg = user_message(code)
        assert msg, f"Empty user_message for {code}"


def test_every_code_has_at_least_one_fix_hint():
    for code in PlannerErrorCode:
        hints = fix_hints(code)
        assert hints and len(hints) >= 1, f"No fix_hints for {code}"
        assert all(h for h in hints), f"Empty hint string for {code}"


def test_error_code_classification_mutually_exclusive_and_complete():
    for code in PlannerErrorCode:
        categories = [is_config_blocking(code), is_transient(code), is_warning_only(code)]
        true_count = sum(categories)
        assert true_count <= 1, (
            f"{code} appears in multiple categories: "
            f"config_blocking={is_config_blocking(code)}, "
            f"transient={is_transient(code)}, "
            f"warning_only={is_warning_only(code)}"
        )


def test_all_codes_are_classified():
    unclassified = [
        code
        for code in PlannerErrorCode
        if not is_config_blocking(code) and not is_transient(code) and not is_warning_only(code)
    ]
    # These should be the "invariant" codes — allowed to be unclassified
    invariant_codes = {
        PlannerErrorCode.NUMERIC_INVALID,
        PlannerErrorCode.SOLVER_INFEASIBLE,
        PlannerErrorCode.SOLVER_UNDEFINED,
        PlannerErrorCode.INVALID_SCHEDULE,
        PlannerErrorCode.INITIAL_SOC_OUT_OF_RANGE,
        PlannerErrorCode.UNKNOWN,
    }
    for code in unclassified:
        assert code in invariant_codes, f"{code} is unclassified and not in invariant set"


def test_is_config_blocking_codes():
    assert is_config_blocking(PlannerErrorCode.CONFIG_INVALID)
    assert is_config_blocking(PlannerErrorCode.EV_MISSING_POWER)
    assert is_config_blocking(PlannerErrorCode.EV_INVALID_CAPACITY)
    assert not is_config_blocking(PlannerErrorCode.INITIAL_SOC_OUT_OF_RANGE)
    assert not is_config_blocking(PlannerErrorCode.PRICES_UNAVAILABLE)


def test_is_transient_codes():
    assert is_transient(PlannerErrorCode.PRICES_UNAVAILABLE)
    assert is_transient(PlannerErrorCode.FORECAST_UNAVAILABLE)
    assert is_transient(PlannerErrorCode.SOLVER_TIMEOUT)
    assert is_transient(PlannerErrorCode.HA_UNAVAILABLE)
    assert not is_transient(PlannerErrorCode.CONFIG_INVALID)


def test_is_warning_only_codes():
    assert is_warning_only(PlannerErrorCode.DATA_STALE)
    assert is_warning_only(PlannerErrorCode.EV_DEADLINE_PAST)
    assert not is_warning_only(PlannerErrorCode.SOLVER_INFEASIBLE)


def test_planner_error_defaults():
    err = PlannerError(code=PlannerErrorCode.CONFIG_INVALID)
    assert err.code == PlannerErrorCode.CONFIG_INVALID
    assert err.message == user_message(PlannerErrorCode.CONFIG_INVALID)
    assert err.fix_hint == fix_hints(PlannerErrorCode.CONFIG_INVALID)[0]
    assert err.details == {}


def test_planner_error_custom_fields():
    err = PlannerError(
        code=PlannerErrorCode.SOLVER_INFEASIBLE,
        message="custom msg",
        fix_hint="custom hint",
        details={"solver_status": "Infeasible"},
    )
    assert err.message == "custom msg"
    assert err.fix_hint == "custom hint"
    assert err.details["solver_status"] == "Infeasible"


def test_planner_error_to_dict():
    err = PlannerError(
        code=PlannerErrorCode.INVALID_SCHEDULE,
        details={"initial_soc_kwh": 18.9},
    )
    d = err.to_dict()
    assert d["code"] == "INVALID_SCHEDULE"
    assert d["message"]
    assert d["fix_hint"]
    assert d["details"]["initial_soc_kwh"] == 18.9


def test_planner_error_is_exception():
    with pytest.raises(PlannerError) as exc_info:
        raise PlannerError(code=PlannerErrorCode.UNKNOWN)
    assert exc_info.value.code == PlannerErrorCode.UNKNOWN
