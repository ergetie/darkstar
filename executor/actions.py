"""
Action Dispatcher

Executes actions by calling Home Assistant services.
Handles idempotent execution (skip if already set) and
notification dispatch per action type.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

from .config import ExecutorConfig
from .controller import ControllerDecision

logger = logging.getLogger(__name__)


def _is_entity_configured(entity: str | None) -> bool:
    """Check if an entity ID is properly configured.

    Returns False if entity is:
    - None
    - Empty string
    - Whitespace only
    - Literal string "None" (case-insensitive)
    """
    if not entity:
        return False
    stripped = entity.strip()
    return stripped != "" and stripped.lower() != "none"


@dataclass
class ActionResult:
    """Result of executing an action."""

    action_type: str
    success: bool
    message: str = ""
    previous_value: Any | None = None
    new_value: Any | None = None
    skipped: bool = False  # True if action was skipped (already at target)
    duration_ms: int = 0


class HAClient:
    """
    Home Assistant API client for executing actions.

    Uses the REST API to call services and get entity states.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: int = 10,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        )

    def get_state(self, entity_id: str) -> dict[str, Any] | None:
        """Get the current state of an entity."""
        # Early validation: catch None/invalid entity_id before hitting HA API
        if not entity_id or (isinstance(entity_id, str) and entity_id.strip().lower() in ("", "none")):
            logger.error(
                "get_state called with invalid entity_id: %r (type: %s) - "
                "check config.yaml for missing entity configuration",
                entity_id,
                type(entity_id).__name__,
            )
            return None

        try:
            response = self._session.get(
                f"{self.base_url}/api/states/{entity_id}",
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error("Failed to get state of %s: %s", entity_id, e)
            return None

    def get_state_value(self, entity_id: str) -> str | None:
        """Get just the state value of an entity."""
        state = self.get_state(entity_id)
        if state:
            return state.get("state")
        return None

    def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> bool:
        """
        Call a Home Assistant service.

        Args:
            domain: Service domain (e.g., 'switch', 'select', 'number')
            service: Service name (e.g., 'turn_on', 'select_option', 'set_value')
            entity_id: Target entity ID (optional)
            data: Additional service data (optional)

        Returns:
            True if successful, False otherwise
        """
        payload = data or {}
        if entity_id:
            payload["entity_id"] = entity_id

        logger.debug(
            "HA call_service: %s.%s on %s with payload: %s", domain, service, entity_id, payload
        )

        try:
            response = self._session.post(
                f"{self.base_url}/api/services/{domain}/{service}",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(
                "Failed to call service %s.%s on %s: %s",
                domain,
                service,
                entity_id,
                e,
            )
            return False

    def set_select_option(self, entity_id: str, option: str) -> bool:
        """Set a select entity to a specific option."""
        return self.call_service("select", "select_option", entity_id, {"option": option})

    def set_switch(self, entity_id: str, state: bool) -> bool:
        """Turn a switch on or off."""
        service = "turn_on" if state else "turn_off"
        return self.call_service("switch", service, entity_id)

    def set_number(self, entity_id: str, value: float) -> bool:
        """Set a number entity to a specific value."""
        return self.call_service("number", "set_value", entity_id, {"value": value})

    def set_input_number(self, entity_id: str, value: float) -> bool:
        """Set an input_number entity to a specific value."""
        return self.call_service("input_number", "set_value", entity_id, {"value": value})

    def send_notification(
        self,
        service: str,
        title: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> bool:
        """
        Send a notification via a notify service.

        Args:
            service: Full notification service name (e.g., 'notify.mobile_app_phone')
            title: Notification title
            message: Notification message
            data: Additional notification data (optional)

        Returns:
            True if successful, False otherwise
        """
        # Parse service name (e.g., "notify.mobile_app_phone" -> domain="notify", service="mobile_app_phone")
        parts = service.split(".", 1)
        if len(parts) != 2:
            logger.error("Invalid notification service format: %s", service)
            return False

        domain, svc_name = parts
        payload: dict[str, Any] = {
            "title": title,
            "message": message,
        }
        if data:
            payload["data"] = data

        return self.call_service(domain, svc_name, data=payload)


class ActionDispatcher:
    """
    Dispatches actions to Home Assistant based on controller decisions.

    Features:
    - Idempotent execution (skip if already at target)
    - Configurable notifications per action type
    - Action result tracking
    """

    def __init__(
        self,
        ha_client: HAClient,
        config: ExecutorConfig,
        shadow_mode: bool = False,
    ):
        self.ha = ha_client
        self.config = config
        self.shadow_mode = shadow_mode

    def execute(self, decision: ControllerDecision) -> list[ActionResult]:
        """
        Execute all actions from a controller decision.

        Args:
            decision: The controller's decision on what actions to take

        Returns:
            List of ActionResult for each action attempted
        """
        results: list[ActionResult] = []

        # 1. Set work mode (Rev O1)
        if self.config.has_battery:
            result = self._set_work_mode(decision.work_mode)
            results.append(result)

        # 2. Set grid charging (Rev O1)
        if self.config.has_battery:
            result = self._set_grid_charging(decision.grid_charging)
            results.append(result)

        # 3. Set charge limit (Rev O1 + E3)
        if self.config.has_battery and decision.write_charge_current:
            result = self._set_charge_limit(decision.charge_value, decision.control_unit)
            results.append(result)

        # 4. Set discharge limit (Rev O1 + E3)
        if self.config.has_battery and decision.write_discharge_current:
            result = self._set_discharge_limit(decision.discharge_value, decision.control_unit)
            results.append(result)

        # 5. Set SoC target (Rev O1)
        if self.config.has_battery:
            result = self._set_soc_target(decision.soc_target)
            results.append(result)

        # 6. Set water heater target (Rev O1)
        if self.config.has_water_heater:
            result = self.set_water_temp(decision.water_temp)
            results.append(result)

        # 7. Set max export power (Bug fix #1)
        if self.config.has_battery:
            result = self._set_max_export_power(decision.export_power_w)
            results.append(result)

        return results

    def _set_work_mode(self, target_mode: str) -> ActionResult:
        """Set inverter work mode if different from current."""
        start = time.time()
        entity = self.config.inverter.work_mode_entity

        if not _is_entity_configured(entity):
            logger.debug("Skipping work_mode action: entity not configured")
            return ActionResult(
                action_type="work_mode",
                success=True,
                message="Work mode entity not configured. Configure in Settings → System → HA Entities",
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        # Get current state
        current = self.ha.get_state_value(entity)

        if current == target_mode:
            return ActionResult(
                action_type="work_mode",
                success=True,
                message=f"Already at {target_mode}",
                previous_value=current,
                new_value=target_mode,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        if self.shadow_mode:
            logger.info("[SHADOW] Would set work_mode to %s (current: %s)", target_mode, current)
            return ActionResult(
                action_type="work_mode",
                success=True,
                message=f"[SHADOW] Would change {current} → {target_mode}",
                previous_value=current,
                new_value=target_mode,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        success = self.ha.set_select_option(entity, target_mode)
        duration = int((time.time() - start) * 1000)

        if success:
            self._maybe_notify("work_mode", f"Work mode changed to {target_mode}")

        return ActionResult(
            action_type="work_mode",
            success=success,
            message=f"Changed {current} → {target_mode}" if success else "Failed to set work mode",
            previous_value=current,
            new_value=target_mode,
            duration_ms=duration,
        )

    def _set_grid_charging(self, enabled: bool) -> ActionResult:
        """Set grid charging switch."""
        start = time.time()
        entity = self.config.inverter.grid_charging_entity

        if not _is_entity_configured(entity):
            logger.debug("Skipping grid_charging action: entity not configured")
            return ActionResult(
                action_type="grid_charging",
                success=True,
                message="Grid charging entity not configured. Configure in Settings → System → HA Entities",
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        current = self.ha.get_state_value(entity)
        target = "on" if enabled else "off"

        if current == target:
            return ActionResult(
                action_type="grid_charging",
                success=True,
                message=f"Already {target}",
                previous_value=current,
                new_value=target,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        if self.shadow_mode:
            logger.info("[SHADOW] Would set grid_charging to %s (current: %s)", target, current)
            return ActionResult(
                action_type="grid_charging",
                success=True,
                message=f"[SHADOW] Would change {current} → {target}",
                previous_value=current,
                new_value=target,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        success = self.ha.set_switch(entity, enabled)
        duration = int((time.time() - start) * 1000)

        action = "start" if enabled else "stop"
        if success:
            self._maybe_notify(f"charge_{action}", f"Grid charging {action}ed")

        return ActionResult(
            action_type="grid_charging",
            success=success,
            message=f"Changed {current} → {target}" if success else "Failed to set grid charging",
            previous_value=current,
            new_value=target,
            duration_ms=duration,
        )

    def _set_charge_limit(self, value: float, unit: str) -> ActionResult:
        """Set max charging limit (Amps or Watts)."""
        start = time.time()

        if unit == "W":
            entity = self.config.inverter.max_charging_power_entity
            unit_label = "W"
        else:
            entity = self.config.inverter.max_charging_current_entity
            unit_label = "A"

        if not _is_entity_configured(entity):
            logger.debug("Skipping charge_limit action: entity not configured for unit %s", unit)
            return ActionResult(
                action_type="charge_limit",
                success=True,
                message=f"Max charge {unit_label} entity not configured. Configure in Settings.",
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        logger.info("Setting charge_limit: %.1f %s on entity: %s", value, unit_label, entity)

        if self.shadow_mode:
            logger.info("[SHADOW] Would set charge_limit to %s %s", value, unit_label)
            return ActionResult(
                action_type="charge_limit",
                success=True,
                message=f"[SHADOW] Would set to {value} {unit_label}",
                new_value=value,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        success = self.ha.set_number(entity, value)
        duration = int((time.time() - start) * 1000)
        logger.info("Set charge_limit result: success=%s, duration=%dms", success, duration)

        return ActionResult(
            action_type="charge_limit",
            success=success,
            message=f"Set to {value} {unit_label}" if success else "Failed to set charge limit",
            new_value=value,
            duration_ms=duration,
        )

    def _set_discharge_limit(self, value: float, unit: str) -> ActionResult:
        """Set max discharging limit (Amps or Watts)."""
        start = time.time()

        if unit == "W":
            entity = self.config.inverter.max_discharging_power_entity
            unit_label = "W"
        else:
            entity = self.config.inverter.max_discharging_current_entity
            unit_label = "A"

        if not _is_entity_configured(entity):
            logger.debug("Skipping discharge_limit action: entity not configured for unit %s", unit)
            return ActionResult(
                action_type="discharge_limit",
                success=True,
                message=f"Max discharge {unit_label} entity not configured. Configure in Settings.",
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        if self.shadow_mode:
            logger.info("[SHADOW] Would set discharge_limit to %s %s", value, unit_label)
            return ActionResult(
                action_type="discharge_limit",
                success=True,
                message=f"[SHADOW] Would set to {value} {unit_label}",
                new_value=value,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        success = self.ha.set_number(entity, value)
        duration = int((time.time() - start) * 1000)

        return ActionResult(
            action_type="discharge_limit",
            success=success,
            message=f"Set to {value} {unit_label}" if success else "Failed to set discharge limit",
            new_value=value,
            duration_ms=duration,
        )

    def _set_soc_target(self, target: int) -> ActionResult:
        """Set SoC target."""
        start = time.time()
        entity = self.config.soc_target_entity

        if not _is_entity_configured(entity):
            logger.debug("Skipping soc_target action: entity not configured")
            return ActionResult(
                action_type="soc_target",
                success=True,
                message="SoC target entity not configured. Configure in Settings → System → HA Entities",
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        current = self.ha.get_state_value(entity)
        try:
            current_val = int(float(current)) if current else None
        except (ValueError, TypeError):
            current_val = None

        if current_val == target:
            return ActionResult(
                action_type="soc_target",
                success=True,
                message=f"Already at {target}%",
                previous_value=current_val,
                new_value=target,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        if self.shadow_mode:
            logger.info(
                "[SHADOW] Would set soc_target to %s%% (current: %s%%)", target, current_val
            )
            return ActionResult(
                action_type="soc_target",
                success=True,
                message=f"[SHADOW] Would change {current_val}% → {target}%",
                previous_value=current_val,
                new_value=target,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        success = self.ha.set_input_number(entity, float(target))
        duration = int((time.time() - start) * 1000)

        if success and self.config.notifications.on_soc_target_change:
            self._send_notification(f"SoC target changed to {target}%")

        return ActionResult(
            action_type="soc_target",
            success=success,
            message=(
                f"Changed {current_val}% → {target}%" if success else "Failed to set SoC target"
            ),
            previous_value=current_val,
            new_value=target,
            duration_ms=duration,
        )

    def set_water_temp(self, target: int) -> ActionResult:
        """Set water heater target temperature."""
        start = time.time()
        entity = self.config.water_heater.target_entity

        if not _is_entity_configured(entity):
            logger.debug("Skipping water_temp action: entity not configured")
            return ActionResult(
                action_type="water_temp",
                success=True,
                message="Water heater target entity not configured. Configure in Settings → System → HA Entities",
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        current = self.ha.get_state_value(entity)
        try:
            current_val = int(float(current)) if current else None
        except (ValueError, TypeError):
            current_val = None

        if current_val == target:
            return ActionResult(
                action_type="water_temp",
                success=True,
                message=f"Already at {target}°C",
                previous_value=current_val,
                new_value=target,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        if self.shadow_mode:
            logger.info(
                "[SHADOW] Would set water_temp to %s°C (current: %s°C)", target, current_val
            )
            return ActionResult(
                action_type="water_temp",
                success=True,
                message=f"[SHADOW] Would change {current_val}°C → {target}°C",
                previous_value=current_val,
                new_value=target,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        success = self.ha.set_input_number(entity, float(target))
        duration = int((time.time() - start) * 1000)

        # Determine if this is start or stop
        is_heating = target > self.config.water_heater.temp_off
        action = "start" if is_heating else "stop"
        if success:
            self._maybe_notify(f"water_heat_{action}", f"Water heater target: {target}°C")

        return ActionResult(
            action_type="water_temp",
            success=success,
            message=(
                f"Changed {current_val}°C → {target}°C" if success else "Failed to set water temp"
            ),
            previous_value=current_val,
            new_value=target,
            duration_ms=duration,
        )

    def _set_max_export_power(self, watts: float) -> ActionResult:
        """Set max grid export power (Bug Fix #1)."""
        start = time.time()
        entity = self.config.inverter.grid_max_export_power_entity

        if not _is_entity_configured(entity):
            logger.debug("Skipping max_export_power action: entity not configured")
            return ActionResult(
                action_type="max_export_power",
                success=True,
                message="Export power entity not configured. Configure in Settings → System → HA Entities",
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        # Check current value and apply write threshold to prevent EEPROM wear
        current = self.ha.get_state_value(entity)
        try:
            current_val = float(current) if current else None
        except (ValueError, TypeError):
            current_val = None

        if current_val is not None:
            change = abs(watts - current_val)
            if change < self.config.controller.write_threshold_w:
                return ActionResult(
                    action_type="max_export_power",
                    success=True,
                    message=f"Change {change:.0f}W < threshold {self.config.controller.write_threshold_w:.0f}W, skipping",
                    previous_value=current_val,
                    new_value=watts,
                    skipped=True,
                    duration_ms=int((time.time() - start) * 1000),
                )

        if self.shadow_mode:
            logger.info("[SHADOW] Would set max_export_power to %s W", watts)
            return ActionResult(
                action_type="max_export_power",
                success=True,
                message=f"[SHADOW] Would set to {watts} W",
                new_value=watts,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        success = self.ha.set_number(entity, watts)
        duration = int((time.time() - start) * 1000)

        logger.info("Set max_export_power: %.0f W on %s (success=%s)", watts, entity, success)

        return ActionResult(
            action_type="max_export_power",
            success=success,
            message=f"Set to {watts} W" if success else "Failed to set export power",
            previous_value=current_val,
            new_value=watts,
            duration_ms=duration,
        )

    def _maybe_notify(self, action_type: str, message: str) -> None:
        """Send notification if enabled for this action type."""
        notif = self.config.notifications

        # Map action types to notification flags
        should_notify = {
            "charge_start": notif.on_charge_start,
            "charge_stop": notif.on_charge_stop,
            "export_start": notif.on_export_start,
            "export_stop": notif.on_export_stop,
            "water_heat_start": notif.on_water_heat_start,
            "water_heat_stop": notif.on_water_heat_stop,
            "work_mode": notif.on_export_start or notif.on_export_stop,
            "override": notif.on_override_activated,
            "error": notif.on_error,
        }.get(action_type, False)

        if should_notify:
            self._send_notification(message)

    def _send_notification(self, message: str, title: str = "Darkstar Executor") -> None:
        """Send a notification via the configured service."""
        if self.shadow_mode:
            logger.info("[SHADOW] Would send notification: %s", message)
            return

        try:
            self.ha.send_notification(
                self.config.notifications.service,
                title,
                message,
            )
        except Exception as e:
            logger.warning("Failed to send notification: %s", e)

    def notify_override(self, override_type: str, reason: str) -> None:
        """Send notification about an override activation."""
        if self.config.notifications.on_override_activated:
            self._send_notification(
                f"Override: {override_type}\n{reason}",
                title="Darkstar Override Active",
            )

    def notify_error(self, error: str) -> None:
        """Send notification about an error."""
        if self.config.notifications.on_error:
            self._send_notification(
                f"Error: {error}",
                title="Darkstar Executor Error",
            )
