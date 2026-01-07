"""
Health Check System

Centralized health monitoring for Darkstar.
Validates HA connection, entity availability, config validity, and planner metrics via SQLite.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytz
import yaml

logger = logging.getLogger(__name__)


@dataclass
class HealthIssue:
    """A single health issue with guidance."""

    category: str  # "ha_connection", "entity", "config", "planner", "executor"
    severity: str  # "critical", "warning", "info"
    message: str  # User-friendly message
    guidance: str  # How to fix
    entity_id: str | None = None  # Specific entity involved (if applicable)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "message": self.message,
            "guidance": self.guidance,
            "entity_id": self.entity_id,
        }


@dataclass
class HealthStatus:
    """Overall system health status."""

    healthy: bool
    issues: list[HealthIssue] = field(default_factory=list[HealthIssue])
    checked_at: str = ""

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = datetime.now(pytz.UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "issues": [issue.to_dict() for issue in self.issues],
            "checked_at": self.checked_at,
            "critical_count": len([i for i in self.issues if i.severity == "critical"]),
            "warning_count": len([i for i in self.issues if i.severity == "warning"]),
        }


class HealthChecker:
    """
    Comprehensive system health checker.

    Validates:
    - Home Assistant connection
    - Configured entity availability
    - Config file validity
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = Path(config_path)
        self._config: dict[str, Any] = {}
        self._secrets: dict[str, Any] = {}

    async def check_all(self) -> HealthStatus:
        """Run all health checks and return combined status."""
        issues: list[HealthIssue] = []

        # Load config first (needed for other checks)
        config_issues = self.check_config_validity()
        issues.extend(config_issues)

        # If config is valid, proceed with other checks
        if not any(i.category == "config" and i.severity == "critical" for i in issues):
            issues.extend(await self.check_ha_connection())

            # Only check entities if HA is connected
            if not any(i.category == "ha_connection" for i in issues):
                issues.extend(await self.check_entities())


        # Check executor health
        issues.extend(self.check_executor())

        # Determine overall health
        has_critical = any(i.severity == "critical" for i in issues)
        healthy = not has_critical

        return HealthStatus(healthy=healthy, issues=issues)

    def check_config_validity(self) -> list[HealthIssue]:
        """Validate config.yaml exists and has required structure."""
        issues: list[HealthIssue] = []

        # Load config
        try:
            with self.config_path.open(encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            issues.append(
                HealthIssue(
                    category="config",
                    severity="critical",
                    message="Configuration file not found",
                    guidance=f"Copy config.default.yaml to {self.config_path} and configure your settings.",
                )
            )
            return issues
        except yaml.YAMLError as e:
            issues.append(
                HealthIssue(
                    category="config",
                    severity="critical",
                    message=f"Invalid YAML syntax in config file: {e}",
                    guidance="Fix the YAML syntax error in config.yaml. Check for incorrect indentation or special characters.",
                )
            )
            return issues

        # Load secrets
        try:
            with Path("secrets.yaml").open(encoding="utf-8") as f:
                self._secrets = yaml.safe_load(f) or {}
        except FileNotFoundError:
            issues.append(
                HealthIssue(
                    category="config",
                    severity="critical",
                    message="Secrets file not found",
                    guidance="Create secrets.yaml with your Home Assistant URL and token. See README for format.",
                )
            )
        except yaml.YAMLError as e:
            issues.append(
                HealthIssue(
                    category="config",
                    severity="critical",
                    message=f"Invalid YAML syntax in secrets file: {e}",
                    guidance="Fix the YAML syntax error in secrets.yaml.",
                )
            )

        # Validate required config sections
        issues.extend(self._validate_config_structure())

        return issues

    def _validate_config_structure(self) -> list[HealthIssue]:
        """Validate config has required sections and correct types."""
        issues: list[HealthIssue] = []

        if not self._config:
            return issues

        # Check battery config
        battery = self._config.get("system", {}).get("battery", {})
        if battery:
            capacity = battery.get("capacity_kwh")
            if capacity is not None and not isinstance(capacity, (int, float)):
                issues.append(
                    HealthIssue(
                        category="config",
                        severity="critical",
                        message=f"Invalid battery capacity: '{capacity}' is not a number",
                        guidance="Set system.battery.capacity_kwh to a numeric value (e.g., 27.0)",
                    )
                )

        # Check input_sensors section exists
        if not self._config.get("input_sensors"):
            issues.append(
                HealthIssue(
                    category="config",
                    severity="warning",
                    message="No input_sensors configured",
                    guidance="Add input_sensors section to config.yaml to enable Home Assistant integration.",
                )
            )

        # Validate HA secrets
        if self._secrets:
            ha_config = self._secrets.get("home_assistant", {})
            if not ha_config.get("url"):
                issues.append(
                    HealthIssue(
                        category="config",
                        severity="critical",
                        message="Home Assistant URL not configured",
                        guidance="Add home_assistant.url to secrets.yaml (e.g., http://homeassistant.local:8123)",
                    )
                )
            if not ha_config.get("token"):
                issues.append(
                    HealthIssue(
                        category="config",
                        severity="critical",
                        message="Home Assistant token not configured",
                        guidance="Add home_assistant.token to secrets.yaml. Generate a Long-Lived Access Token in HA.",
                    )
                )

        return issues

    async def check_ha_connection(self) -> list[HealthIssue]:
        """Check if Home Assistant is reachable."""
        issues: list[HealthIssue] = []

        if not self._secrets:
            return issues  # Already reported in config check

        ha_config = self._secrets.get("home_assistant", {})
        url = ha_config.get("url", "").rstrip("/")
        token = ha_config.get("token", "")

        if not url or not token:
            return issues  # Already reported in config check

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{url}/api/",
                    headers={"Authorization": f"Bearer {token}"},
                )

            if response.status_code == 401:
                issues.append(
                    HealthIssue(
                        category="ha_connection",
                        severity="critical",
                        message="Home Assistant authentication failed",
                        guidance="Your HA token is invalid or expired. Generate a new Long-Lived Access Token in HA → Profile → Security.",
                    )
                )
            elif response.status_code != 200:
                issues.append(
                    HealthIssue(
                        category="ha_connection",
                        severity="critical",
                        message=f"Home Assistant returned error: HTTP {response.status_code}",
                        guidance="Check that your Home Assistant URL is correct and HA is running.",
                    )
                )

        except httpx.TimeoutException:
            issues.append(
                HealthIssue(
                    category="ha_connection",
                    severity="critical",
                    message="Home Assistant connection timed out",
                    guidance="Home Assistant is slow or unreachable. Check network connectivity.",
                )
            )
        except httpx.RequestError as e:
            issues.append(
                HealthIssue(
                    category="ha_connection",
                    severity="critical",
                    message=f"Cannot connect to Home Assistant: {e}",
                    guidance=f"Check that Home Assistant is running and reachable at {url}",
                )
            )
        except Exception as e:
            issues.append(
                HealthIssue(
                    category="ha_connection",
                    severity="critical",
                    message=f"Unexpected error connecting to HA: {e}",
                    guidance="Check your network and Home Assistant configuration.",
                )
            )

        return issues

    async def check_entities(self) -> list[HealthIssue]:
        """Check if configured entities exist in Home Assistant."""
        issues: list[HealthIssue] = []

        if not self._config or not self._secrets:
            return issues

        ha_config = self._secrets.get("home_assistant", {})
        url = ha_config.get("url", "").rstrip("/")
        token = ha_config.get("token", "")

        if not url or not token:
            return issues

        # Collect all entity IDs from config
        entities_to_check: list[tuple[str, str]] = []  # (entity_id, config_key)

        # Input sensors
        input_sensors = self._config.get("input_sensors", {})
        for key, entity_id in input_sensors.items():
            if entity_id and isinstance(entity_id, str):
                entities_to_check.append((entity_id, f"input_sensors.{key}"))

        # Executor entities
        executor = self._config.get("executor", {})
        if executor:
            # Inverter entities
            inverter = executor.get("inverter", {})
            for key in [
                "work_mode_entity",
                "grid_charging_entity",
                "max_charging_current_entity",
                "max_discharging_current_entity",
            ]:
                entity_id = inverter.get(key)
                if entity_id:
                    entities_to_check.append((entity_id, f"executor.inverter.{key}"))

            # Water heater
            water = executor.get("water_heater", {})
            target_entity = water.get("target_entity")
            if target_entity:
                entities_to_check.append((target_entity, "executor.water_heater.target_entity"))

            # Toggle entities
            for key in ["automation_toggle_entity", "soc_target_entity"]:
                entity_id = executor.get(key)
                if entity_id:
                    entities_to_check.append((entity_id, f"executor.{key}"))

        # Check each entity
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=5.0) as client:
            for entity_id, config_key in entities_to_check:
                try:
                    response = await client.get(
                        f"{url}/api/states/{entity_id}",
                        headers=headers,
                    )

                    if response.status_code == 404:
                        issues.append(
                            HealthIssue(
                                category="entity",
                                severity="critical",
                                message=f"Entity not found: {entity_id}",
                                guidance=f"Check that '{entity_id}' exists in Home Assistant. Update {config_key} in config.yaml if renamed.",
                                entity_id=entity_id,
                            )
                        )
                    elif response.status_code == 200:
                        # Check for unavailable state
                        state_data = response.json()
                        state_value = state_data.get("state")
                        if state_value == "unavailable":
                            issues.append(
                                HealthIssue(
                                    category="entity",
                                    severity="warning",
                                    message=f"Entity unavailable: {entity_id}",
                                    guidance=f"The entity '{entity_id}' exists but is currently unavailable. Check your device/integration.",
                                    entity_id=entity_id,
                                )
                            )
                except httpx.RequestError:
                    # Connection issues already reported in check_ha_connection
                    pass

        return issues


    def check_executor(self) -> list[HealthIssue]:
        """Check executor health status."""
        issues: list[HealthIssue] = []

        try:
            from backend.api.routers.executor import get_executor_health

            executor_health = get_executor_health()

            if not executor_health["is_healthy"]:
                if executor_health["should_be_running"] and not executor_health["is_running"]:
                    issues.append(
                        HealthIssue(
                            category="executor",
                            severity="critical",
                            message="Executor should be running but is not active",
                            guidance="The executor is enabled in config but not running. Check executor logs or restart the service.",
                        )
                    )
                elif executor_health["has_error"]:
                    error_msg = executor_health.get("error", "Unknown error")
                    issues.append(
                        HealthIssue(
                            category="executor",
                            severity="warning",
                            message=f"Executor last run failed: {error_msg}",
                            guidance="Check executor logs for details. The error may be transient or indicate a configuration issue.",
                        )
                    )
        except Exception as e:
            logger.debug("Could not check executor health: %s", e)
            # Don't add an issue - executor health check is optional

        return issues


async def get_health_status(config_path: str = "config.yaml") -> HealthStatus:
    """Convenience function to get current health status."""
    checker = HealthChecker(config_path)
    return await checker.check_all()
