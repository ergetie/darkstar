"""Tests for HealthIssue serialization and planner health check."""

from unittest.mock import MagicMock, patch

from backend.health import (
    HealthChecker,
    HealthIssue,
    clear_load_forecast_status,
    set_load_forecast_status,
)


class TestHealthIssueSerialization:
    def test_without_new_fields_omits_keys(self):
        issue = HealthIssue(
            category="config",
            severity="critical",
            message="Test issue",
            guidance="Fix it",
        )
        d = issue.to_dict()
        assert "code" not in d
        assert "details" not in d
        assert "retry_in_s" not in d
        assert d["category"] == "config"
        assert d["severity"] == "critical"

    def test_with_all_new_fields_serializes(self):
        issue = HealthIssue(
            category="planner",
            severity="critical",
            message="Config invalid",
            guidance="Check battery settings",
            entity_id=None,
            code="CONFIG_INVALID",
            details={"field": "capacity_kwh", "value": 0},
            retry_in_s=120,
        )
        d = issue.to_dict()
        assert d["code"] == "CONFIG_INVALID"
        assert d["details"]["field"] == "capacity_kwh"
        assert d["retry_in_s"] == 120

    def test_entity_id_none_omits_key(self):
        issue = HealthIssue(
            category="config",
            severity="warning",
            message="Test",
            guidance="Fix",
        )
        d = issue.to_dict()
        assert "entity_id" not in d


class TestCheckPlanner:
    def test_no_planner_error_returns_empty(self):
        checker = HealthChecker()
        mock_svc = MagicMock()
        mock_svc.last_error_code = None
        with patch("backend.services.planner_service.planner_service", mock_svc):
            issues = checker.check_planner()
            assert issues == []

    def test_config_blocking_error_returns_critical(self):
        from planner.errors import PlannerErrorCode

        checker = HealthChecker()
        mock_svc = MagicMock()
        mock_svc.last_error_code = PlannerErrorCode.CONFIG_INVALID
        mock_svc.last_error_details = {"field": "capacity_kwh"}
        mock_svc.retry_in_s = None
        with patch("backend.services.planner_service.planner_service", mock_svc):
            issues = checker.check_planner()
            assert len(issues) == 1
            assert issues[0].severity == "critical"
            assert issues[0].code == "CONFIG_INVALID"
            assert issues[0].details == {"field": "capacity_kwh"}
            assert issues[0].category == "planner"

    def test_transient_error_returns_warning_with_retry(self):
        from planner.errors import PlannerErrorCode

        checker = HealthChecker()
        mock_svc = MagicMock()
        mock_svc.last_error_code = PlannerErrorCode.PRICES_UNAVAILABLE
        mock_svc.last_error_details = {"observed_horizon_hours": 2.0}
        mock_svc.retry_in_s = 120
        with patch("backend.services.planner_service.planner_service", mock_svc):
            issues = checker.check_planner()
            assert len(issues) == 1
            assert issues[0].severity == "warning"
            assert issues[0].code == "PRICES_UNAVAILABLE"
            assert issues[0].retry_in_s == 120

    def test_active_suspension_is_critical_even_without_last_error(self):
        checker = HealthChecker()
        mock_svc = MagicMock()
        mock_svc.retry_suspended = True
        mock_svc.last_error_code = None
        with patch("backend.services.planner_service.planner_service", mock_svc):
            issues = checker.check_planner()

        assert len(issues) == 1
        assert issues[0].category == "planner"
        assert issues[0].severity == "critical"
        assert "suspended" in issues[0].message.lower()

    def test_active_suspension_remains_critical_after_prior_error(self):
        from planner.errors import PlannerErrorCode

        checker = HealthChecker()
        mock_svc = MagicMock()
        mock_svc.retry_suspended = True
        mock_svc.last_error_code = PlannerErrorCode.CONFIG_INVALID
        mock_svc.last_error_details = {"field": "capacity_kwh"}
        with patch("backend.services.planner_service.planner_service", mock_svc):
            issues = checker.check_planner()

        assert len(issues) == 1
        assert issues[0].category == "planner"
        assert issues[0].severity == "critical"
        assert issues[0].code == PlannerErrorCode.CONFIG_INVALID.value


class TestCheckLoadForecast:
    def teardown_method(self):
        clear_load_forecast_status()

    def test_not_configured_message_instructs_configuration(self):
        clear_load_forecast_status()
        set_load_forecast_status("degraded", "demo")
        checker = HealthChecker()
        issues = checker.check_load_forecast()
        assert len(issues) == 1
        assert "demo data" in issues[0].message
        assert "Configure" in issues[0].guidance
        assert "discarded" not in issues[0].guidance

    def test_configured_but_discarded_message_names_sensor_not_configure(self):
        clear_load_forecast_status()
        set_load_forecast_status(
            "degraded",
            "demo",
            detail=(
                "'sensor.fronius_lifetime' data discarded: 19609.2 kWh/day exceeds the "
                "500 kWh/day plausibility bound"
            ),
        )
        checker = HealthChecker()
        issues = checker.check_load_forecast()
        assert len(issues) == 1
        assert "sensor.fronius_lifetime" in issues[0].guidance
        assert "500 kWh/day plausibility bound" in issues[0].guidance
        assert "total_load_consumption" not in issues[0].guidance


class TestNoCounterSensorRequirement:
    """Learning-enabled installs without the removed counter keys stay healthy."""

    async def test_no_missing_sensor_issue_for_removed_counters(self):
        from unittest.mock import AsyncMock

        checker = HealthChecker()
        checker._secrets = {"home_assistant": {"url": "http://ha.local", "token": "tok"}}
        checker._config = {
            "learning": {"enable": True},
            "system": {
                "grid_meter_type": "net",
                "has_battery": True,
                "has_solar": True,
                "has_water_heater": False,
            },
            "input_sensors": {
                "battery_soc": "sensor.soc",
                "load_power": "sensor.load",
                "pv_power": "sensor.pv",
                "grid_power": "sensor.grid",
                "battery_power": "sensor.batt",
            },
        }
        response = MagicMock(status_code=200)
        response.json.return_value = {"state": "1.0"}
        client = MagicMock()
        client.get = AsyncMock(return_value=response)

        with patch("backend.core.ha_client.get_ha_http_client", return_value=client):
            issues = await checker.check_entities()

        assert issues == []
        # Only the configured power sensors are looked up, no counters
        requested = {call.args[0].rsplit("/", 1)[1] for call in client.get.await_args_list}
        assert requested == {
            "sensor.soc",
            "sensor.load",
            "sensor.pv",
            "sensor.grid",
            "sensor.batt",
        }
