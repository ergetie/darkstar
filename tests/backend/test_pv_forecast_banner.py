"""PV forecast outage banner: text carries the estimated slot count, severity escalates."""

import pytest

from backend import health
from backend.health import HealthChecker, clear_forecast_errors, record_forecast_error


@pytest.fixture(autouse=True)
def _reset_forecast_errors():
    clear_forecast_errors()
    yield
    clear_forecast_errors()


def _record(estimated: int, total: int) -> None:
    record_forecast_error(
        RuntimeError("API unreachable — using last known forecast"),
        context={"estimated_slots": estimated, "total_slots": total},
    )


def test_banner_text_includes_estimated_count():
    _record(5, 48)
    (issue,) = HealthChecker().check_forecast()
    assert issue.message == "API unreachable — using last known forecast (5 slots estimated)"
    assert issue.severity == "warning"


def test_banner_is_warning_at_exactly_half():
    _record(24, 48)
    (issue,) = HealthChecker().check_forecast()
    assert issue.severity == "warning"


def test_banner_is_critical_above_half():
    _record(25, 48)
    (issue,) = HealthChecker().check_forecast()
    assert issue.severity == "critical"
    assert "(25 slots estimated)" in issue.message
    assert health.PV_ESTIMATED_CRITICAL_FRACTION == 0.5


def test_degraded_without_context_keeps_generic_warning():
    record_forecast_error(RuntimeError("something else"))
    (issue,) = HealthChecker().check_forecast()
    assert issue.severity == "warning"
    assert issue.message == "PV forecast experiencing issues"
