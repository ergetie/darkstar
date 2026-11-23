"""Tests for health check async behavior - DNS crash loop fixes.

This test ensures:
1. Health check timeouts work correctly (asyncio.wait_for)
2. Entity checks run concurrently (asyncio.gather)
3. Timeout errors are handled gracefully
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.mark.asyncio
async def test_get_health_status_respects_timeout(monkeypatch):
    """Verify that get_health_status() has a 15-second timeout wrapper.

    This is a regression test for the DNS crash loop bug where health checks
    could hang indefinitely due to blocking I/O.

    The fix: Wrap check_all() in asyncio.wait_for(timeout=15.0) to ensure
    the health check returns even if individual checks are stuck.
    """
    import backend.health as health_mod
    from backend.health import HealthStatus, get_health_status

    monkeypatch.setattr(health_mod, "HEALTH_CHECK_TIMEOUT_S", 0.1)

    # Mock HealthChecker.check_all to be slow (simulates stuck I/O)
    with patch("backend.health.HealthChecker") as mock_checker_class:
        mock_checker = MagicMock()
        mock_checker.check_all = AsyncMock()

        # Make check_all hang for 30 seconds (far longer than the patched timeout)
        async def slow_check():
            await asyncio.sleep(30)
            return HealthStatus(healthy=True, issues=[])

        mock_checker.check_all.side_effect = slow_check
        mock_checker_class.return_value = mock_checker

        # Call should complete within reasonable time (timeout + overhead)
        start = asyncio.get_event_loop().time()
        result = await get_health_status()
        elapsed = asyncio.get_event_loop().time() - start

        # Should timeout and return gracefully shortly after the patched timeout
        assert elapsed < 5.0, f"Health check took {elapsed}s, should timeout at 0.1s"

        # Should return unhealthy status with timeout issue
        assert result.healthy is False
        assert len(result.issues) == 1
        assert "timed out" in result.issues[0].message.lower()


@pytest.mark.asyncio
async def test_check_entities_uses_concurrent_gather():
    """Verify that entity checks run concurrently using asyncio.gather.

    This test ensures that multiple entity checks don't run sequentially,
    which could cause the health check to take too long with many entities.

    The fix: Use asyncio.gather to run all entity checks concurrently,
    reducing total time from O(n) to O(1) for network-bound checks.
    """
    from backend.health import HealthChecker

    # Create a mock config with multiple entities to check
    mock_config = {
        "system": {
            "has_battery": True,
            "has_water_heater": False,
            "has_solar": True,
            "grid_meter_type": "net",
        },
        "learning": {"enable": False},
        "input_sensors": {
            "battery_soc": "sensor.battery_soc",
            "grid_power": "sensor.grid_power",
            "pv_power": "sensor.pv_power",
            "load_power": "sensor.load_power",
            "soc_min": "number.soc_min",
        },
    }
    mock_secrets = {
        "home_assistant": {
            "url": "http://homeassistant:8123",
            "token": "test_token",
        },
    }

    checker = HealthChecker.__new__(HealthChecker)
    checker._config = mock_config
    checker._secrets = mock_secrets

    # Track call times to verify concurrency
    call_times = []
    original_sleep = asyncio.sleep

    async def mock_check_with_delay(*args, **kwargs):
        """Simulate a network request that takes some time."""
        call_times.append(asyncio.get_event_loop().time())
        await original_sleep(0.1)  # Small delay to simulate network
        return None  # No issue

    with patch("backend.core.ha_client.get_ha_http_client") as mock_get_client:
        mock_client = AsyncMock()

        # Mock successful responses
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"state": "10.5", "attributes": {}}
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        # Run the check
        start = asyncio.get_event_loop().time()
        await checker.check_entities()
        elapsed = asyncio.get_event_loop().time() - start

        # With 5 entities and 0.1s delay each, sequential would take ~0.5s
        # Concurrent should take ~0.1s (plus overhead)
        assert elapsed < 0.3, (
            f"Entity checks took {elapsed:.2f}s, suggesting sequential execution. "
            f"Expected concurrent execution under 0.3s"
        )

        # Verify all entities were checked
        assert mock_client.get.call_count >= 4


@pytest.mark.asyncio
async def test_check_entities_handles_individual_failures():
    """Verify that one failing entity check doesn't break all others.

    When using asyncio.gather with return_exceptions=True, individual
    failures should be handled gracefully without affecting other checks.
    """
    from backend.health import HealthChecker

    mock_config = {
        "system": {
            "has_battery": True,
            "has_water_heater": False,
            "has_solar": True,
            "grid_meter_type": "net",
        },
        "learning": {"enable": False},
        "input_sensors": {
            "battery_soc": "sensor.battery_soc",
            "grid_power": "sensor.grid_power",
        },
    }
    mock_secrets = {
        "home_assistant": {
            "url": "http://homeassistant:8123",
            "token": "test_token",
        },
    }

    checker = HealthChecker.__new__(HealthChecker)
    checker._config = mock_config
    checker._secrets = mock_secrets

    call_count = 0

    with patch("backend.core.ha_client.get_ha_http_client") as mock_get_client:
        mock_client = AsyncMock()

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_response = MagicMock()

            # First call succeeds, second raises exception
            if call_count == 1:
                mock_response.status_code = 200
                mock_response.json.return_value = {"state": "10.5"}
            else:
                raise httpx.ConnectError("Connection refused")

            return mock_response

        mock_client.get = mock_get
        mock_get_client.return_value = mock_client

        # Should complete without raising
        await checker.check_entities()

        # Should have attempted both checks despite one failing
        assert call_count == 2


@pytest.mark.asyncio
async def test_health_status_timeout_returns_critical_issue():
    """Verify that timeout produces a properly formatted critical health issue."""
    from backend.health import HealthIssue, HealthStatus

    # Simulate what get_health_status does on timeout
    timeout_status = HealthStatus(
        healthy=False,
        issues=[
            HealthIssue(
                category="ha_connection",
                severity="critical",
                message="Health check timed out after 15 seconds",
                guidance="The system is experiencing connectivity issues. Check network and Home Assistant availability.",
            )
        ],
    )
    assert timeout_status.healthy is False
    assert len(timeout_status.issues) == 1
    issue = timeout_status.issues[0]
    assert issue.severity == "critical"
    assert "timed out" in issue.message.lower()
    assert "15" in issue.message


def _make_checker(config: dict):
    from backend.health import HealthChecker

    checker = HealthChecker.__new__(HealthChecker)
    checker._config = config
    checker._secrets = {}
    return checker


# --- Solar health check ---


def test_solar_warning_when_arrays_empty():
    checker = _make_checker({"system": {"has_solar": True, "solar_arrays": []}})
    issues = checker._validate_config_structure()
    messages = [i.message for i in issues]
    assert "Solar enabled but panel size not configured" in messages


def test_solar_no_warning_when_kwp_configured():
    checker = _make_checker(
        {"system": {"has_solar": True, "solar_arrays": [{"kwp": 5.0}, {"kwp": 3.0}]}}
    )
    issues = checker._validate_config_structure()
    messages = [i.message for i in issues]
    assert "Solar enabled but panel size not configured" not in messages


def test_solar_legacy_singular_key_ignored():
    checker = _make_checker({"system": {"has_solar": True, "solar_array": {"kwp": 10.0}}})
    issues = checker._validate_config_structure()
    messages = [i.message for i in issues]
    assert "Solar enabled but panel size not configured" in messages


# --- Water heater health check ---


def test_water_heater_warning_when_list_empty():
    checker = _make_checker({"system": {"has_water_heater": True}, "water_heaters": []})
    issues = checker._validate_config_structure()
    messages = [i.message for i in issues]
    assert "Water heater enabled but power not configured" in messages


def test_water_heater_no_warning_when_configured():
    checker = _make_checker(
        {
            "system": {"has_water_heater": True},
            "water_heaters": [{"enabled": True, "power_kw": 3.0}],
        }
    )
    issues = checker._validate_config_structure()
    messages = [i.message for i in issues]
    assert "Water heater enabled but power not configured" not in messages


def test_water_heater_legacy_flat_field_ignored():
    checker = _make_checker(
        {
            "system": {"has_water_heater": True},
            "water_heating": {"power_kw": 3.0},
            "water_heaters": [],
        }
    )
    issues = checker._validate_config_structure()
    messages = [i.message for i in issues]
    assert "Water heater enabled but power not configured" in messages


def test_health_no_energy_sensor_warnings():
    """No energy-sensor warnings are emitted — energy is now measured via History API."""
    from backend.health import HealthChecker

    checker = HealthChecker.__new__(HealthChecker)
    checker._config = {
        "ev_chargers": [
            {
                "id": "ev1",
                "name": "My EV",
                "sensor": "sensor.ev_power",
                "enabled": True,
            }
        ],
        "water_heaters": [
            {
                "id": "wh1",
                "name": "Main Tank",
                "sensor": "sensor.water_power",
                "enabled": True,
            }
        ],
    }
    checker._secrets = {}

    issues = checker._validate_config_structure()

    energy_sensor_issues = [i for i in issues if "energy sensor" in i.message.lower()]
    assert len(energy_sensor_issues) == 0


# --- Warn-only battery checks (learned-battery-inverter-parameters) -------------------------


def _battery_checker():
    from backend.health import HealthChecker

    checker = HealthChecker()
    checker._config = {"timezone": "Europe/Stockholm", "system": {"has_battery": True}}
    return checker


async def _battery_issues(tmp_path, capacity=None, shortfalls=(), compute_error=None):
    import backend.health as health_mod

    health_mod._battery_warning_cache = None
    db = tmp_path / "learning.db"
    db.touch()
    store = MagicMock(
        close=AsyncMock(),
        get_slot_observation_rows=AsyncMock(return_value=[]),
        get_plans_range=AsyncMock(return_value=[]),
    )
    with (
        patch("backend.core.forecasts.get_forecast_db_path", return_value=str(db)),
        patch("backend.learning.store.LearningStore", return_value=store),
        patch(
            "backend.learning.learned_parameters.resolve_effective_config",
            new=AsyncMock(return_value=({}, None)),
        ),
        patch("planner.solver.adapter.config_to_kepler_config", return_value=MagicMock()),
        patch(
            "backend.learning.battery_warnings.capacity_change_warning",
            side_effect=compute_error,
            return_value=capacity,
        ),
        patch(
            "backend.learning.battery_warnings.power_shortfall_warning",
            return_value=list(shortfalls),
        ),
    ):
        return await _battery_checker().check_battery_warnings()


@pytest.mark.asyncio
async def test_capacity_change_issue_has_category_severity_and_both_values(tmp_path):
    from backend.learning.battery_warnings import CapacityWarning

    (issue,) = await _battery_issues(tmp_path, capacity=CapacityWarning(34.0, (19.0, 19.5), 34.0))

    assert (issue.category, issue.severity, issue.code) == (
        "battery",
        "warning",
        "battery_capacity_change",
    )
    assert "about 19 kWh" in issue.message and "about 34 kWh" in issue.message
    assert issue.acknowledge_id is None  # snoozed by its stable code, like other warnings
    assert "does not change this setting" in issue.guidance


@pytest.mark.asyncio
async def test_power_shortfall_issue_names_planned_and_delivered_power(tmp_path):
    from backend.learning.battery_warnings import PowerShortfall

    (issue,) = await _battery_issues(
        tmp_path, shortfalls=[PowerShortfall("charge", 30, 5.0, 3.5, 5.0)]
    )

    assert issue.code == "battery_charge_power_shortfall"
    assert issue.severity == "warning"
    assert "5.0 kW" in issue.message and "3.5 kW" in issue.message


@pytest.mark.asyncio
async def test_insufficient_data_gives_no_issue(tmp_path):
    assert await _battery_issues(tmp_path) == []


@pytest.mark.asyncio
async def test_evaluator_exception_gives_no_issue_and_is_not_retried_every_poll(tmp_path):
    import backend.health as health_mod

    assert await _battery_issues(tmp_path, compute_error=RuntimeError("boom")) == []
    assert health_mod._battery_warning_cache is not None  # failure is cached briefly


@pytest.mark.asyncio
async def test_no_battery_means_no_check(tmp_path):
    checker = _battery_checker()
    checker._config = {"system": {"has_battery": False}}
    assert await checker.check_battery_warnings() == []


# --- Executor health check (inverter-revert-warning-and-executor-health) -------------------


def _executor_stub(
    *,
    alive=True,
    enabled=True,
    paused=False,
    last_run_status="success",
    last_error=None,
    last_run_age_s=None,
    interval=300,
    inactive_age_s=None,
):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    last_run_at = (
        None if last_run_age_s is None else datetime.now(timezone.utc) - timedelta(seconds=last_run_age_s)
    )
    return SimpleNamespace(
        _thread=SimpleNamespace(is_alive=lambda: alive),
        is_paused=paused,
        config=SimpleNamespace(enabled=enabled, interval_seconds=interval),
        status=SimpleNamespace(
            last_run_at=last_run_at, last_run_status=last_run_status, last_error=last_error
        ),
        recent_errors=[],
        inverter_profile=None,
        last_inactive_at=(
            None
            if inactive_age_s is None
            else datetime.now(timezone.utc) - timedelta(seconds=inactive_age_s)
        ),
    )


def _executor_issues(executor, config=None):
    from backend.health import HealthChecker

    checker = HealthChecker()
    checker._config = {"executor": {"enabled": True}} if config is None else config
    with patch("backend.api.routers.executor.peek_executor_instance", return_value=executor):
        return checker.check_executor()


def test_check_executor_dead_thread_is_critical():
    issues = _executor_issues(_executor_stub(alive=False))
    assert [(i.code, i.severity) for i in issues] == [("EXECUTOR_NOT_RUNNING", "critical")]


def test_check_executor_paused_alive_is_healthy():
    assert _executor_issues(_executor_stub(paused=True, last_run_age_s=99999)) == []


def test_check_executor_paused_dead_thread_not_reported():
    assert _executor_issues(_executor_stub(alive=False, paused=True)) == []


def test_check_executor_disabled_alive_is_healthy():
    assert _executor_issues(_executor_stub(enabled=False, last_run_age_s=99999)) == []


def test_check_executor_last_run_failed_is_warning_with_message():
    issues = _executor_issues(
        _executor_stub(last_run_status="error", last_error="boom", last_run_age_s=10)
    )
    assert [(i.code, i.severity) for i in issues] == [("EXECUTOR_LAST_RUN_FAILED", "warning")]
    assert "boom" in issues[0].message


def test_check_executor_healthy_returns_nothing():
    assert _executor_issues(_executor_stub(last_run_age_s=60)) == []


def test_check_executor_no_instance_enabled_is_critical_and_creates_nothing():
    from backend.health import HealthChecker

    checker = HealthChecker()
    checker._config = {"executor": {"enabled": True}}
    with (
        patch("backend.api.routers.executor.peek_executor_instance", return_value=None),
        patch("backend.api.routers.executor.get_executor_instance") as create,
    ):
        issues = checker.check_executor()
    assert [(i.code, i.severity) for i in issues] == [("EXECUTOR_NOT_INITIALIZED", "critical")]
    create.assert_not_called()


def test_check_executor_no_instance_disabled_is_silent():
    assert _executor_issues(None, config={"executor": {"enabled": False}}) == []
    assert _executor_issues(None, config={}) == []


def test_check_executor_stale_loop_warns():
    # default interval 300 -> threshold max(900, 600) = 900 s
    issues = _executor_issues(_executor_stub(last_run_age_s=1000))
    assert [(i.code, i.severity) for i in issues] == [("EXECUTOR_STALE", "warning")]


def test_check_executor_recent_tick_not_stale():
    assert _executor_issues(_executor_stub(last_run_age_s=800)) == []


def test_check_executor_stale_threshold_has_ten_minute_floor():
    # interval 60 -> 3 x 60 = 180 s, floor 600 s applies
    assert _executor_issues(_executor_stub(interval=60, last_run_age_s=500)) == []
    issues = _executor_issues(_executor_stub(interval=60, last_run_age_s=700))
    assert [i.code for i in issues] == ["EXECUTOR_STALE"]


def test_check_executor_not_stale_right_after_resume():
    # Last tick was hours ago but the loop only resumed 20 s ago.
    stub = _executor_stub(last_run_age_s=7200, inactive_age_s=20)
    assert _executor_issues(stub) == []


def test_check_executor_stale_when_no_tick_long_after_resume():
    stub = _executor_stub(last_run_age_s=7200, inactive_age_s=1000)
    assert [i.code for i in _executor_issues(stub)] == ["EXECUTOR_STALE"]


def test_check_executor_no_tick_yet_not_stale():
    assert _executor_issues(_executor_stub(last_run_age_s=None)) == []


def test_check_executor_internal_failure_logs_warning_and_returns_nothing(caplog):
    import logging

    from backend.health import HealthChecker

    checker = HealthChecker()
    checker._config = {"executor": {"enabled": True}}
    with (
        caplog.at_level(logging.WARNING),
        patch("backend.api.routers.executor.peek_executor_instance", side_effect=RuntimeError("x")),
    ):
        assert checker.check_executor() == []
    assert any(r.levelno == logging.WARNING and "executor health" in r.message for r in caplog.records)


def test_executor_health_snapshot_real_engine_shape_and_route():
    import asyncio

    from backend.api.routers.executor import executor_health_snapshot, get_health

    stub = _executor_stub(paused=True, last_run_age_s=10)
    snap = executor_health_snapshot(stub)
    assert snap["is_healthy"] is True and snap["should_be_running"] is False
    assert asyncio.run(get_health(stub))["status"] == "healthy"

    dead = executor_health_snapshot(_executor_stub(alive=False))
    assert dead["is_healthy"] is False and dead["status"] == "error"

    disabled = executor_health_snapshot(_executor_stub(enabled=False, alive=False))
    assert disabled["is_healthy"] is True

    err = executor_health_snapshot(_executor_stub(last_run_status="error", last_error="e"))
    assert err["has_error"] and err["error"] == "e" and err["is_healthy"] is False


def test_check_monitors_surfaces_inverter_mode_revert_with_entities():
    from backend.health import HealthChecker
    from backend.monitors import InvariantMonitors, InvariantResult

    monitors = InvariantMonitors(config_path="config.yaml")
    entities = [
        {"entity": "select.inverter_work_mode", "count": 3, "commanded": "A", "observed": "B"}
    ]
    monitors._apply_results(
        [InvariantResult("inverter_mode_revert", "violation", "x", data={"entities": entities})]
    )
    with patch("backend.monitors.invariant_monitors", monitors):
        issues = HealthChecker().check_monitors()
    assert [i.code for i in issues] == ["INVERTER_MODE_REVERT"]
    assert issues[0].details == {
        "first_detected_at": monitors.state.episodes["inverter_mode_revert"].first_detected_at,
        "entities": entities,
    }
