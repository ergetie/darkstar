"""
Health Check System

Centralized health monitoring for Darkstar.
Validates HA connection, entity availability, config validity, and database connectivity.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz
import requests
import yaml

logger = logging.getLogger(__name__)


@dataclass
class HealthIssue:
    """A single health issue with guidance."""

    category: str  # "ha_connection", "entity", "config", "database", "planner", "executor"
    severity: str  # "critical", "warning", "info"
    message: str  # User-friendly message
    guidance: str  # How to fix
    entity_id: Optional[str] = None  # Specific entity involved (if applicable)

    def to_dict(self) -> Dict[str, Any]:
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
    issues: List[HealthIssue] = field(default_factory=list)
    checked_at: str = ""

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = datetime.now(pytz.UTC).isoformat()

    def to_dict(self) -> Dict[str, Any]:
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
    - Database connectivity
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self._config: Optional[Dict] = None
        self._secrets: Optional[Dict] = None

    def check_all(self) -> HealthStatus:
        """Run all health checks and return combined status."""
        issues: List[HealthIssue] = []

        # Load config first (needed for other checks)
        config_issues = self.check_config_validity()
        issues.extend(config_issues)

        # If config is valid, proceed with other checks
        if not any(i.category == "config" and i.severity == "critical" for i in issues):
            issues.extend(self.check_ha_connection())

            # Only check entities if HA is connected
            if not any(i.category == "ha_connection" for i in issues):
                issues.extend(self.check_entities())

        issues.extend(self.check_database())

        # Determine overall health
        has_critical = any(i.severity == "critical" for i in issues)
        healthy = not has_critical

        return HealthStatus(healthy=healthy, issues=issues)

    def check_config_validity(self) -> List[HealthIssue]:
        """Validate config.yaml exists and has required structure."""
        issues: List[HealthIssue] = []

        # Load config
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
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
            with open("secrets.yaml", "r", encoding="utf-8") as f:
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

    def _validate_config_structure(self) -> List[HealthIssue]:
        """Validate config has required sections and correct types."""
        issues: List[HealthIssue] = []

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

    def check_ha_connection(self) -> List[HealthIssue]:
        """Check if Home Assistant is reachable."""
        issues: List[HealthIssue] = []

        if not self._secrets:
            return issues  # Already reported in config check

        ha_config = self._secrets.get("home_assistant", {})
        url = ha_config.get("url", "").rstrip("/")
        token = ha_config.get("token", "")

        if not url or not token:
            return issues  # Already reported in config check

        try:
            response = requests.get(
                f"{url}/api/",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
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

        except requests.exceptions.ConnectionError:
            issues.append(
                HealthIssue(
                    category="ha_connection",
                    severity="critical",
                    message="Cannot connect to Home Assistant",
                    guidance=f"Check that Home Assistant is running and reachable at {url}",
                )
            )
        except requests.exceptions.Timeout:
            issues.append(
                HealthIssue(
                    category="ha_connection",
                    severity="critical",
                    message="Home Assistant connection timed out",
                    guidance="Home Assistant is slow or unreachable. Check network connectivity.",
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

    def check_entities(self) -> List[HealthIssue]:
        """Check if configured entities exist in Home Assistant."""
        issues: List[HealthIssue] = []

        if not self._config or not self._secrets:
            return issues

        ha_config = self._secrets.get("home_assistant", {})
        url = ha_config.get("url", "").rstrip("/")
        token = ha_config.get("token", "")

        if not url or not token:
            return issues

        # Collect all entity IDs from config
        entities_to_check: List[tuple] = []  # (entity_id, config_key)

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
            for key in ["work_mode_entity", "grid_charging_entity", "max_charging_current_entity", "max_discharging_current_entity"]:
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
        for entity_id, config_key in entities_to_check:
            try:
                response = requests.get(
                    f"{url}/api/states/{entity_id}",
                    headers=headers,
                    timeout=5,
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

            except requests.exceptions.RequestException:
                # Connection issues already reported in check_ha_connection
                pass

        return issues

    def check_database(self) -> List[HealthIssue]:
        """Check database connectivity."""
        issues: List[HealthIssue] = []

        if not self._secrets:
            return issues

        db_config = self._secrets.get("mariadb", {})
        if not db_config:
            # Database is optional, just note it
            issues.append(
                HealthIssue(
                    category="database",
                    severity="info",
                    message="No database configured",
                    guidance="Database is optional. Add mariadb section to secrets.yaml to enable historical data.",
                )
            )
            return issues

        try:
            import pymysql

            connection = pymysql.connect(
                host=db_config.get("host", "localhost"),
                port=db_config.get("port", 3306),
                user=db_config.get("user", ""),
                password=db_config.get("password", ""),
                database=db_config.get("database", ""),
                connect_timeout=5,
            )
            connection.close()

        except ImportError:
            # pymysql not installed, skip db check
            pass
        except Exception as e:
            issues.append(
                HealthIssue(
                    category="database",
                    severity="warning",
                    message=f"Database connection failed: {e}",
                    guidance="Check your database credentials in secrets.yaml. Historical data features will be limited.",
                )
            )

        return issues


def get_health_status(config_path: str = "config.yaml") -> HealthStatus:
    """Convenience function to get current health status."""
    checker = HealthChecker(config_path)
    return checker.check_all()
