"""Lifecycle: first adoption, step limit, deadband, once per local day, lock, rejection."""

from datetime import datetime, timedelta

import pytest

from backend.learning import learned_parameters as lp
from backend.learning.battery_estimators import KEY_CHARGE_LOSS, KEY_RTE, KEY_STANDBY_W, Estimate
from tests.learning.battery_synth import TZ

NOW = TZ.localize(datetime(2026, 3, 10, 1, 0))


def _estimate(value: float, confidence: float = 0.9) -> Estimate:
    return Estimate(value=value, confidence=confidence, evidence={"days": 30})


def _state(key: str = KEY_RTE, **kwargs) -> lp.ParameterState:
    return lp.ParameterState(key=key, **kwargs)


def test_first_adoption_is_direct() -> None:
    result = lp.apply_estimate(_state(), _estimate(0.962), NOW)

    assert result.state.applied_value == 0.962
    assert result.state.learned_value == 0.962
    assert result.state.estimated_at == NOW and result.state.applied_at == NOW
    [event] = result.events
    assert (event.event, event.old_value, event.new_value) == (lp.EVENT_LEARNED, None, 0.962)
    assert event.notify_state == lp.NOTIFY_PENDING


def test_step_limit_moves_by_exactly_one_step() -> None:
    state = _state(
        applied_value=0.96, applied_at=NOW - timedelta(days=1), estimated_at=NOW - timedelta(days=1)
    )
    result = lp.apply_estimate(state, _estimate(0.98), NOW)

    assert result.state.applied_value == pytest.approx(0.97)
    assert result.state.learned_value == 0.98
    assert result.events[0].old_value == 0.96


def test_deadband_skips_without_history() -> None:
    state = _state(applied_value=0.960, applied_at=NOW - timedelta(days=1))
    result = lp.apply_estimate(state, _estimate(0.9615), NOW)

    assert result.state.applied_value == 0.960
    assert result.state.applied_at == state.applied_at
    assert result.state.learned_value == 0.9615
    assert result.events == []


def test_second_update_the_same_local_day_is_skipped() -> None:
    state = _state(applied_value=0.90, applied_at=NOW - timedelta(hours=1))
    result = lp.apply_estimate(state, _estimate(0.96), NOW)

    assert result.state.applied_value == 0.90
    assert result.events == []
    assert result.state.estimated_at == NOW  # the estimate itself is still accepted


def test_local_day_boundary_uses_the_local_date() -> None:
    late = TZ.localize(datetime(2026, 3, 9, 23, 50))
    state = _state(applied_value=0.90, applied_at=late)
    result = lp.apply_estimate(state, _estimate(0.96), NOW)  # 01:00 next local day

    assert result.state.applied_value == pytest.approx(0.91)


def test_rejected_estimate_keeps_values_and_estimated_at() -> None:
    estimated = NOW - timedelta(days=5)
    state = _state(
        learned_value=0.95, applied_value=0.95, estimated_at=estimated, evidence={"days": 40}
    )
    rejected = Estimate(
        value=None, confidence=0.0, evidence={"days": 3}, rejected_reason="3 usable days, 28 needed"
    )

    result = lp.apply_estimate(state, rejected, NOW)

    assert result.state.estimated_at == estimated
    assert result.state.applied_value == 0.95 and result.state.learned_value == 0.95
    assert result.state.status_note == "3 usable days, 28 needed"
    assert result.state.evidence["days"] == 40
    assert result.state.evidence["last_rejection"]["reason"] == "3 usable days, 28 needed"
    assert result.events == []


def test_accepted_estimate_clears_the_note_and_old_rejection() -> None:
    state = _state(status_note="old", evidence={"last_rejection": {"reason": "x"}})
    result = lp.apply_estimate(state, _estimate(0.95), NOW)

    assert result.state.status_note is None
    assert "last_rejection" not in result.state.evidence


def test_locked_parameter_keeps_applied_value_but_learns() -> None:
    state = _state(
        applied_value=0.90, applied_at=NOW - timedelta(days=2), locked=True, locked_value=0.93
    )
    result = lp.apply_estimate(state, _estimate(0.96), NOW)

    assert result.state.applied_value == 0.90
    assert result.state.learned_value == 0.96
    assert result.state.estimated_at == NOW
    assert result.events == []


@pytest.mark.parametrize(
    ("key", "step", "deadband"),
    [(KEY_RTE, 0.01, 0.002), (KEY_CHARGE_LOSS, 0.01, 0.002), (KEY_STANDBY_W, 20.0, 5.0)],
)
def test_step_and_deadband_constants(key: str, step: float, deadband: float) -> None:
    assert lp.PARAMETERS[key].step == step
    assert lp.PARAMETERS[key].deadband == deadband


def test_standby_moves_in_watt_steps() -> None:
    state = _state(KEY_STANDBY_W, applied_value=40.0, applied_at=NOW - timedelta(days=1))
    result = lp.apply_estimate(state, _estimate(100.0), NOW)
    assert result.state.applied_value == 60.0
