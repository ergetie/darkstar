"""
Action Dispatcher

Executes actions by calling Home Assistant services asynchronously using aiohttp.
Handles idempotent execution (skip if already set), notification dispatch per action type,
and automatic retry with exponential backoff for transient network failures.

Key Features:
- Async HTTP client (aiohttp) for non-blocking HA API calls
- 5-second timeout on all requests to prevent executor freezing
- Exponential backoff retry (3 attempts) for transient network errors
- Graceful degradation when HA is unreachable
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aiohttp

from .config import ExecutorConfig
from .controller import ControllerDecision
from .profiles import InverterProfile, ModeAction

logger = logging.getLogger(__name__)


class HACallError(Exception):
    """Home Assistant API call error with detailed context."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_body: str | None = None,
        exception_type: str | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.response_body = response_body
        self.exception_type = exception_type

        error_parts = [message]
        if status_code is not None:
            error_parts.append(f"HTTP {status_code}")
        if response_body:
            error_parts.append(f"Response: {response_body}")
        if exception_type:
            error_parts.append(f"({exception_type})")

        super().__init__(" | ".join(error_parts))


def _is_retryable_error(exception: Exception) -> bool:
    """Check if an exception is retryable (transient network error).

    Retryable errors include:
    - Connection errors (connection reset, refused, etc.)
    - Timeout errors
    - Server errors (5xx)
    - Temporary network issues

    Non-retryable errors include:
    - Client errors (4xx except 429)
    - Authentication errors
    - Invalid URL errors
    """
    import aiohttp

    # Server errors (5xx) are retryable
    if isinstance(exception, aiohttp.ClientResponseError):
        return exception.status >= 500 or exception.status == 429  # 429 = Too Many Requests

    # Connection and timeout errors are retryable
    return isinstance(exception, aiohttp.ClientError | asyncio.TimeoutError)


async def _retry_with_backoff(
    operation: Callable[[], Any],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    backoff_factor: float = 2.0,
) -> Any:
    """Execute an async operation with exponential backoff retry.

    Args:
        operation: Async callable to execute
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay: Initial delay between retries in seconds (default: 1.0)
        max_delay: Maximum delay between retries in seconds (default: 10.0)
        backoff_factor: Multiplier for exponential backoff (default: 2.0)

    Returns:
        Result of the operation

    Raises:
        HACallError: If all retries are exhausted
        Exception: If the error is not retryable
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return await operation()
        except Exception as e:
            last_exception = e

            # Check if this is the last attempt
            if attempt >= max_retries:
                break

            # Check if error is retryable
            if not _is_retryable_error(e):
                # Not retryable, raise immediately
                raise

            # Calculate delay with exponential backoff
            delay = min(base_delay * (backoff_factor**attempt), max_delay)
            logger.warning(
                "HA API call failed (attempt %d/%d): %s. Retrying in %.1fs...",
                attempt + 1,
                max_retries + 1,
                e,
                delay,
            )
            await asyncio.sleep(delay)

    # All retries exhausted
    raise HACallError(
        message=f"HA API call failed after {max_retries + 1} attempts",
        exception_type=type(last_exception).__name__ if last_exception else "Unknown",
    ) from last_exception


def _parse_bool_value(value: Any) -> bool:
    """Interpret a switch/input_boolean write value against the on/off string
    convention used throughout config (on_value/off_value, e.g. "1"/"0"),
    rather than Python truthiness (bool("0") is True, which would always turn
    the entity on).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "on", "yes")
    return bool(value)


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


# Standard inverter entity keys that live directly in executor.inverter.*
# Any profile entity key NOT in this set goes into executor.inverter.custom_entities.*
_STANDARD_INVERTER_KEYS: frozenset[str] = frozenset(
    [
        "work_mode",
        "soc_target",
        "grid_charging_enable",
        "grid_charge_power",
        "minimum_reserve",
        "grid_max_export_power",
        "grid_max_export_power_switch",
        "max_charge_current",
        "max_discharge_current",
        "max_charge_power",
        "max_discharge_power",
    ]
)


@dataclass
class ActionResult:
    """Result of executing an action."""

    action_type: str
    success: bool
    message: str = ""
    previous_value: Any | None = None
    new_value: Any | None = None
    entity_id: str | None = None  # NEW: The HA entity being controlled
    verified_value: Any | None = None  # NEW: Value read back after setting
    verification_success: bool | None = None  # NEW: Whether verification matched expected value
    skipped: bool = False  # True if action was skipped (already at target)
    duration_ms: int = 0
    error_details: str | None = None  # REV F52 Phase 5: HA API error details (status, body, etc.)
    # ARC16: Track the controller's intended mode vs applied mode
    requested_mode: str | None = None  # The mode_intent from controller (e.g., "idle")
    applied_mode: str | None = None  # The actual mode whose entities were applied


class HAClient:
    """
    Async Home Assistant API client for executing actions.

    Uses aiohttp for non-blocking HTTP communication with Home Assistant.
    All methods are async and should be awaited.

    Features:
    - Connection pooling via aiohttp.ClientSession
    - Configurable timeout (default: 5 seconds)
    - Automatic retry with exponential backoff for transient errors
    - Graceful error handling with HACallError exceptions

    Usage:
        client = HAClient("http://homeassistant:8123", "token")
        state = await client.get_state("sensor.battery_soc")
        await client.close()
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: int = 5,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._sessions: dict[asyncio.AbstractEventLoop, aiohttp.ClientSession] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session for the CURRENT running event loop.

        One session per event loop — a session is never closed from a
        different loop than the one that created it (closing cross-loop
        raises "Future attached to a different loop"). A stale/foreign-loop
        session is simply left alone in ``_sessions``; only the current
        loop's session is touched here.
        """
        current_loop = asyncio.get_running_loop()

        session = self._sessions.get(current_loop)
        if session is None or session.closed:
            session = aiohttp.ClientSession(
                headers=self._headers,
                timeout=self.timeout,
            )
            self._sessions[current_loop] = session

        return session

    async def close(self) -> None:
        """Close the aiohttp session belonging to the CURRENT running event loop."""
        current_loop = asyncio.get_running_loop()
        session = self._sessions.pop(current_loop, None)
        if session and not session.closed:
            await session.close()

    async def get_state(self, entity_id: str) -> dict[str, Any] | None:
        """Get the current state of an entity with retry logic."""
        # Early validation: catch None/invalid entity_id before hitting HA API
        if not entity_id or entity_id.strip().lower() in ("", "none"):
            logger.error(
                "get_state called with invalid entity_id: %r (type: %s) - "
                "check config.yaml for missing entity configuration",
                entity_id,
                type(entity_id).__name__,
            )
            return None

        async def _fetch() -> dict[str, Any]:
            session = await self._get_session()
            async with session.get(
                f"{self.base_url}/api/states/{entity_id}",
            ) as response:
                response.raise_for_status()
                return await response.json()

        try:
            return await _retry_with_backoff(_fetch, max_retries=3, base_delay=1.0)
        except HACallError:
            # All retries exhausted, return None for graceful degradation
            return None

    async def get_state_value(self, entity_id: str) -> str | None:
        """Get just the state value of an entity."""
        state = await self.get_state(entity_id)
        if state:
            return state.get("state")
        return None

    async def call_service(
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
            True if successful

        Raises:
            HACallError: If the API call fails
        """
        payload = data or {}
        if entity_id:
            payload["entity_id"] = entity_id

        logger.debug(
            "HA call_service: %s.%s on %s with payload: %s", domain, service, entity_id, payload
        )

        async def _post() -> None:
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/api/services/{domain}/{service}",
                json=payload,
            ) as response:
                response.raise_for_status()

        try:
            await _retry_with_backoff(_post, max_retries=3, base_delay=1.0)
            return True
        except aiohttp.ClientResponseError as e:
            raise HACallError(
                message=f"Failed to call service {domain}.{service} on {entity_id}",
                status_code=e.status,
                response_body=str(e.message),
                exception_type=type(e).__name__,
            ) from e
        except (aiohttp.ClientError, TimeoutError) as e:
            raise HACallError(
                message=f"Failed to call service {domain}.{service} on {entity_id}",
                exception_type=type(e).__name__,
            ) from e

    def _get_safe_domain(self, entity_id: str, allowed_domains: set[str]) -> str | None:
        """
        Get the domain from an entity ID and validate it is safe to control.

        Args:
            entity_id: The HA entity ID (e.g., 'input_select.mode')
            allowed_domains: Set of allowed domains (e.g., {'select', 'input_select'})

        Returns:
            The domain string if valid, None if invalid or unsafe.
        """
        if not entity_id:
            return None

        parts = entity_id.split(".", 1)
        if len(parts) != 2:
            logger.error("Invalid entity_id format: %s", entity_id)
            return None

        domain = parts[0]

        # Explicit safety guard against sensors
        if domain in ("sensor", "binary_sensor"):
            logger.error(
                "SAFETY GUARD: Cannot control read-only entity '%s'. "
                "Check config.yaml and use a controllable entity (e.g., input_number, helper).",
                entity_id,
            )
            return None

        if domain not in allowed_domains:
            logger.error(
                "Domain '%s' not allowed for this action. Allowed: %s. Entity: %s",
                domain,
                allowed_domains,
                entity_id,
            )
            return None

        return domain

    async def set_select_option(self, entity_id: str, option: str) -> bool:
        """Set a select entity to a specific option."""
        domain = self._get_safe_domain(entity_id, {"select", "input_select"})
        if not domain:
            raise HACallError(
                message=f"Invalid domain for select entity {entity_id}",
                exception_type="DomainValidationError",
            )
        return await self.call_service(domain, "select_option", entity_id, {"option": option})

    async def set_switch(self, entity_id: str, state: bool) -> bool:
        """Turn a switch on or off."""
        domain = self._get_safe_domain(entity_id, {"switch", "input_boolean"})
        if not domain:
            raise HACallError(
                message=f"Invalid domain for switch entity {entity_id}",
                exception_type="DomainValidationError",
            )
        service = "turn_on" if state else "turn_off"
        return await self.call_service(domain, service, entity_id)

    async def set_number(self, entity_id: str, value: float) -> bool:
        """Set a number entity to a specific value."""
        domain = self._get_safe_domain(entity_id, {"number", "input_number"})
        if not domain:
            raise HACallError(
                message=f"Invalid domain for number entity {entity_id}",
                exception_type="DomainValidationError",
            )
        return await self.call_service(domain, "set_value", entity_id, {"value": value})

    async def set_input_number(self, entity_id: str, value: float) -> bool:
        """Set an input_number entity to a specific value."""
        # Alias to set_number which now handles both
        return await self.set_number(entity_id, value)

    async def set_input_datetime(self, entity_id: str, dt: datetime) -> bool:
        """Set an input_datetime entity to a specific datetime."""
        domain = self._get_safe_domain(entity_id, {"input_datetime"})
        if not domain:
            raise HACallError(
                message=f"Invalid domain for input_datetime entity {entity_id}",
                exception_type="DomainValidationError",
            )
        dt_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        return await self.call_service(domain, "set_datetime", entity_id, {"datetime": dt_str})

    async def send_notification(
        self,
        service: str | None,
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
        if not service:
            return False

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

        return await self.call_service(domain, svc_name, data=payload)


class ActionDispatcher:
    """
    Dispatches actions to Home Assistant based on controller decisions.

    Uses profile-driven architecture where each mode defines an ordered list
    of entity+value actions. The executor is a generic loop.

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
        profile: InverterProfile | None = None,
    ):
        self.ha = ha_client
        self.config = config
        self.shadow_mode = shadow_mode
        self.profile = profile

    def _resolve_entity_id(self, key: str) -> str | None:
        """
        Resolve entity key to actual HA entity ID.

        Resolution order:
        1. User override: executor.inverter.custom_entities[key]
        2. Standard config: executor.inverter[key]
        3. Profile default: entities[key].default_entity
        """
        if not self.profile:
            return None

        entity_def = self.profile.entities.get(key)
        if not entity_def:
            return None

        override = self.config.inverter.custom_entities.get(key)
        if override:
            return override

        standard = getattr(self.config.inverter, key, None)
        if standard:
            return standard

        return entity_def.default_entity

    def _resolve_value(self, value: str | int | float | bool, decision: ControllerDecision) -> Any:
        """
        Resolve dynamic template values from ControllerDecision.

        Templates are strings in the form {{field_name}} where field_name
        is a property on ControllerDecision.
        """
        if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
            field_name = value[2:-2]
            if not hasattr(decision, field_name):
                logger.error("Unknown template variable: %s", field_name)
                return value
            return getattr(decision, field_name)
        return value

    async def _write_entity(
        self,
        entity_id: str,
        value: Any,
        domain: str,
    ) -> bool:
        """
        Write value to HA entity using appropriate service call.

        Args:
            entity_id: The HA entity ID to write to
            value: The value to write
            domain: The HA domain (select, number, switch, input_number)

        Returns:
            True if successful
        """
        try:
            if domain in ("number", "input_number"):
                return await self.ha.set_number(entity_id, float(value))
            elif domain == "select":
                return await self.ha.set_select_option(entity_id, str(value))
            elif domain in ("switch", "input_boolean"):
                # bool("0") is True in Python — on_value/off_value are configured
                # as "1"/"0" strings, so a naive bool(value) would always turn
                # the switch on. Interpret the on/off convention explicitly.
                return await self.ha.set_switch(entity_id, _parse_bool_value(value))
            else:
                logger.error("Unknown entity domain: %s", domain)
                return False
        except HACallError as e:
            logger.error("Failed to write to %s: %s", entity_id, e)
            return False

    def _values_match(self, current: str | None, target: Any) -> bool:
        """Check if current value matches target value."""
        if current is None:
            return False
        try:
            current_float = float(current)
            target_float = float(target)
            return abs(current_float - target_float) < 0.01
        except (ValueError, TypeError):
            if isinstance(target, bool) or (
                isinstance(target, str)
                and target.strip().lower() in ("0", "1", "true", "false", "on", "off", "yes", "no")
            ):
                target_bool = _parse_bool_value(target)
                current_lower = str(current).strip().lower()
                if target_bool and current_lower == "on":
                    return True
                if not target_bool and current_lower == "off":
                    return True
            return str(current).strip().lower() == str(target).strip().lower()

    async def _verify_action(self, entity_id: str, expected: Any) -> tuple[Any, bool | None]:
        """Verify that an action was applied correctly."""
        state = await self.ha.get_state_value(entity_id)
        if state is None:
            return None, None

        matches = self._values_match(state, expected)
        return state, matches

    async def execute(self, decision: ControllerDecision) -> list[ActionResult]:
        """
        Execute all actions from a controller decision using profile-driven approach.

        Args:
            decision: The controller's decision with mode_intent

        Returns:
            List of ActionResult for each action attempted
        """
        if not self.profile:
            logger.error("No profile loaded - cannot execute actions")
            return [
                ActionResult(
                    action_type="error",
                    success=False,
                    message="No inverter profile loaded",
                )
            ]

        mode_intent = decision.mode_intent

        try:
            mode_def = self.profile.get_mode(mode_intent)
        except Exception as e:
            logger.error("Failed to get mode '%s' from profile: %s", mode_intent, e)
            return [
                ActionResult(
                    action_type="error",
                    success=False,
                    message=f"Profile error: {e}",
                )
            ]

        logger.info(
            "Executing mode '%s' (%s) for profile '%s'",
            mode_intent,
            mode_def.description,
            self.profile.metadata.name,
        )

        results: list[ActionResult] = []

        for action in mode_def.actions:
            result = await self._execute_action(action, decision, mode_intent)
            results.append(result)

            if action.settle_ms and action.settle_ms > 0:
                logger.debug("Settle delay: %dms after %s", action.settle_ms, action.entity)
                await asyncio.sleep(action.settle_ms / 1000.0)

        if results:
            successful = sum(1 for r in results if r.success)
            logger.info(
                "Mode '%s' executed: %d/%d actions successful",
                mode_intent,
                successful,
                len(results),
            )

        return results

    async def _execute_action(
        self,
        action: ModeAction,
        decision: ControllerDecision,
        mode_intent: str,
    ) -> ActionResult:
        """Execute a single mode action."""
        start_time = time.time()

        if not self.profile:
            return ActionResult(
                action_type=action.entity,
                success=False,
                message="No profile loaded",
                requested_mode=mode_intent,
                applied_mode=mode_intent,
                duration_ms=int((time.time() - start_time) * 1000),
            )

        entity_def = self.profile.entities.get(action.entity)
        if not entity_def:
            return ActionResult(
                action_type=action.entity,
                success=False,
                message=f"Entity '{action.entity}' not defined in profile",
                requested_mode=mode_intent,
                applied_mode=mode_intent,
                duration_ms=int((time.time() - start_time) * 1000),
            )

        entity_id = self._resolve_entity_id(action.entity)

        if not entity_id:
            return ActionResult(
                action_type=action.entity,
                success=False,
                message=f"Entity '{action.entity}' not configured",
                requested_mode=mode_intent,
                applied_mode=mode_intent,
                duration_ms=int((time.time() - start_time) * 1000),
            )

        resolved_value = self._resolve_value(action.value, decision)

        previous_value = await self.ha.get_state_value(entity_id)

        if self._values_match(previous_value, resolved_value):
            return ActionResult(
                action_type=action.entity,
                success=True,
                message=f"Already at {resolved_value}",
                previous_value=previous_value,
                new_value=resolved_value,
                entity_id=entity_id,
                skipped=True,
                requested_mode=mode_intent,
                applied_mode=mode_intent,
                duration_ms=int((time.time() - start_time) * 1000),
            )

        if self.shadow_mode:
            logger.info(
                "[SHADOW] Would set %s to %s (current: %s)",
                entity_id,
                resolved_value,
                previous_value,
            )
            return ActionResult(
                action_type=action.entity,
                success=True,
                message=f"[SHADOW] Would change {previous_value} → {resolved_value}",
                previous_value=previous_value,
                new_value=resolved_value,
                entity_id=entity_id,
                skipped=True,
                requested_mode=mode_intent,
                applied_mode=mode_intent,
                duration_ms=int((time.time() - start_time) * 1000),
            )

        success = await self._write_entity(entity_id, resolved_value, entity_def.domain)

        verified_value = None
        verification_success = None
        if success:
            verified_value, verification_success = await self._verify_action(
                entity_id, resolved_value
            )

        duration_ms = int((time.time() - start_time) * 1000)

        if success:
            await self._maybe_notify(action.entity, f"Set {action.entity} to {resolved_value}")

        return ActionResult(
            action_type=action.entity,
            success=success,
            message=f"{previous_value} → {resolved_value}"
            if success
            else f"Failed to set {action.entity}",
            previous_value=previous_value,
            new_value=resolved_value,
            entity_id=entity_id,
            verified_value=verified_value,
            verification_success=verification_success,
            requested_mode=mode_intent,
            applied_mode=mode_intent,
            duration_ms=duration_ms,
        )

    async def set_water_temp(self, target: int, target_entity: str | None = None) -> ActionResult:
        """Set water heater target temperature.

        Args:
            target: Target temperature in °C
            target_entity: HA entity to control. If None, falls back to
                           config.water_heater.target_entity (legacy single-heater path).
        """
        start = time.time()
        # Use passed entity; fall back to legacy single-entity config for backward compat
        entity = (
            target_entity
            if target_entity is not None
            else getattr(self.config.water_heater, "target_entity", None)
        )

        if not _is_entity_configured(entity):
            logger.debug("Skipping water_temp action: entity not configured")
            return ActionResult(
                action_type="water_temp",
                success=True,
                message="Water heater target entity not configured. Configure in Settings → System → HA Entities",
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
                error_details=None,
            )

        assert entity is not None  # guaranteed by _is_entity_configured guard above
        current = await self.ha.get_state_value(entity)
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
                entity_id=entity,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
                error_details=None,
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
                entity_id=entity,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
                error_details=None,
            )

        error_details = None
        try:
            success = await self.ha.set_input_number(entity, float(target))  # type: ignore[arg-type]
        except HACallError as e:
            success = False
            error_details = str(e)
            logger.error("Failed to set water_temp: %s", error_details)

        # Verification
        verified_value = None
        verification_success = None
        if success:
            v_val, v_ok = await self._verify_action(entity, target)  # type: ignore[arg-type]
            verification_success = v_ok
            try:
                verified_value = int(float(v_val)) if v_val else None
            except (ValueError, TypeError):
                verified_value = v_val

        duration = int((time.time() - start) * 1000)

        # Determine if this is start or stop
        is_heating = target > self.config.water_heater.temp_off
        action = "start" if is_heating else "stop"
        if success:
            await self._maybe_notify(f"water_heat_{action}", f"Water heater target: {target}°C")

        return ActionResult(
            action_type="water_temp",
            success=success,
            message=(
                f"Changed {current_val}°C → {target}°C"
                if success
                else f"Failed: {error_details}"
                if error_details
                else "Failed to set water temp"
            ),
            previous_value=current_val,
            new_value=target,
            entity_id=entity,
            verified_value=verified_value,
            verification_success=verification_success,
            duration_ms=duration,
            error_details=error_details,
        )

    async def set_balanced_entity(self, entity_id: str, value: str) -> ActionResult:
        """Write an on/off value to a custom HA entity (excess-PV custom_entity
        sinks and load-balancing custom-entity loads both use this generic,
        entity_id-parametrized helper — see engine.py's iteration over
        `excess_pv.priority[]` custom_entity entries and `load_balancing.loads[]`).
        """
        start = time.time()
        current = await self.ha.get_state_value(entity_id)

        if self._values_match(current, value):
            return ActionResult(
                action_type="balanced_load_entity",
                success=True,
                message=f"Already at {value}",
                previous_value=current,
                new_value=value,
                entity_id=entity_id,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        if self.shadow_mode:
            logger.info(
                "[SHADOW] Would set balanced load entity %s to %s (current: %s)",
                entity_id,
                value,
                current,
            )
            return ActionResult(
                action_type="balanced_load_entity",
                success=True,
                message=f"[SHADOW] Would change {current} -> {value}",
                previous_value=current,
                new_value=value,
                entity_id=entity_id,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
            )

        error_details = None
        try:
            domain = entity_id.split(".", 1)[0] if "." in entity_id else "switch"
            success = await self._write_entity(entity_id, value, domain)
        except HACallError as e:
            success = False
            error_details = str(e)
            logger.error("Failed to set balanced load entity %s: %s", entity_id, error_details)

        duration = int((time.time() - start) * 1000)

        return ActionResult(
            action_type="balanced_load_entity",
            success=success,
            message=(
                f"Set {entity_id} to {value}"
                if success
                else f"Failed: {error_details}"
                if error_details
                else "Failed to set balanced load entity"
            ),
            previous_value=current,
            new_value=value,
            entity_id=entity_id,
            duration_ms=duration,
            error_details=error_details,
        )

    async def _set_max_export_power(self, watts: float) -> ActionResult | None:
        """Set max grid export power."""
        start = time.time()

        entity = self.config.inverter.grid_max_export_power

        # Check if profile supports grid export limit via entity registry
        if self.profile and "grid_max_export_power" not in self.profile.entities:
            logger.debug(
                "Skipping max_export_power action: profile '%s' does not define grid_max_export_power entity",
                self.profile.metadata.name,
            )
            return None  # Silent skip - no entry in execution history

        if not _is_entity_configured(entity):
            # Check if this entity is actually required by the profile
            is_required = True
            if self.profile and "grid_max_export_power" in self.profile.entities:
                is_required = self.profile.entities["grid_max_export_power"].required

            if not is_required:
                # Silent skip - not configured and not required
                return None  # Silent skip - no entry in execution history

            logger.debug("Skipping max_export_power action: entity not configured")
            return ActionResult(
                action_type="max_export_power",
                success=True,
                message="Export power entity not configured. Configure in Settings → System → HA Entities",
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
                error_details=None,
            )

        # Check current value and apply write threshold to prevent EEPROM wear
        if entity is None:
            return ActionResult(
                action_type="max_export_power",
                success=False,
                message="Entity is None after validation",
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
                error_details=None,
            )

        current = await self.ha.get_state_value(entity)
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
                    entity_id=entity,
                    skipped=True,
                    duration_ms=int((time.time() - start) * 1000),
                    error_details=None,
                )

        if self.shadow_mode:
            logger.info("[SHADOW] Would set max_export_power to %s W", watts)
            return ActionResult(
                action_type="max_export_power",
                success=True,
                message=f"[SHADOW] Would set to {watts} W",
                new_value=watts,
                entity_id=entity,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
                error_details=None,
            )

        error_details = None
        try:
            success = await self.ha.set_number(entity, watts)
        except HACallError as e:
            success = False
            error_details = str(e)
            logger.error("Failed to set max_export_power: %s", error_details)

        # Verification
        verified_value = None
        verification_success = None
        if success:
            verified_value, verification_success = await self._verify_action(entity, watts)

        # 5. Handle Export Switch (F49)
        # If a switch is configured, turn it ON when setting a limit.
        # This ensures that inverter actually enforces the numeric value.
        switch_entity = self.config.inverter.grid_max_export_power_switch
        if success and _is_entity_configured(switch_entity) and switch_entity is not None:
            logger.info("Enabling export power limit switch: %s", switch_entity)
            try:
                await self.ha.set_switch(switch_entity, True)
            except HACallError as e:
                logger.warning("Failed to enable export power limit switch: %s", str(e))

        duration = int((time.time() - start) * 1000)

        logger.info("Set max_export_power: %.0f W on %s (success=%s)", watts, entity, success)

        return ActionResult(
            action_type="max_export_power",
            success=success,
            message=f"Set to {watts} W"
            if success
            else f"Failed: {error_details}"
            if error_details
            else "Failed to set export power",
            previous_value=current_val,
            new_value=watts,
            entity_id=entity,
            verified_value=verified_value,
            verification_success=verification_success,
            duration_ms=duration,
            error_details=error_details,
        )

    async def set_ev_charger_switch(
        self, entity_id: str, turn_on: bool, charging_kw: float = 0.0
    ) -> ActionResult:
        """
        Control EV charger switch with shadow mode support.

        Args:
            entity_id: The HA switch entity ID for the EV charger
            turn_on: True to turn on, False to turn off
            charging_kw: Planned charging power in kW (for logging/notifications)

        Returns:
            ActionResult with details of the action
        """
        start = time.time()
        action_type = "ev_charge_start" if turn_on else "ev_charge_stop"
        action_label = "ON" if turn_on else "OFF"

        # Check current state
        current_state = await self.ha.get_state_value(entity_id)
        is_currently_on = current_state == "on" if current_state else False

        # Idempotent skip
        if turn_on == is_currently_on:
            return ActionResult(
                action_type=action_type,
                success=True,
                message=f"EV charger already {action_label}",
                previous_value=current_state,
                new_value=turn_on,
                entity_id=entity_id,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
                error_details=None,
            )

        # Shadow mode check
        if self.shadow_mode:
            logger.info(
                "[SHADOW] EV Charger: Would turn %s %s (current: %s)",
                action_label,
                entity_id,
                current_state,
            )
            return ActionResult(
                action_type=action_type,
                success=True,
                message=f"[SHADOW] Would turn {action_label}",
                previous_value=current_state,
                new_value=turn_on,
                entity_id=entity_id,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
                error_details=None,
            )

        # Execute action
        error_details = None
        try:
            await self.ha.set_switch(entity_id, turn_on)
            success = True
        except HACallError as e:
            success = False
            error_details = str(e)
            logger.error("Failed to control EV charger %s: %s", entity_id, error_details)

        # Verification
        verified_value = None
        verification_success = None
        if success:
            verified_value, verification_success = await self._verify_action(
                entity_id, "on" if turn_on else "off"
            )

        duration = int((time.time() - start) * 1000)

        # Notification (via _maybe_notify)
        if turn_on:
            await self._maybe_notify(
                "ev_charge_start", f"EV charging started ({charging_kw:.1f} kW)"
            )
        else:
            await self._maybe_notify("ev_charge_stop", "EV charging stopped")

        return ActionResult(
            action_type=action_type,
            success=success,
            message=f"EV charger turned {action_label}"
            if success
            else f"Failed: {error_details}"
            if error_details
            else f"Failed to turn {action_label} EV charger",
            previous_value=current_state,
            new_value=turn_on,
            entity_id=entity_id,
            verified_value=verified_value,
            verification_success=verification_success,
            duration_ms=duration,
            error_details=error_details,
        )

    async def set_ev_charger_current(self, entity_id: str, amps: int) -> ActionResult:
        """
        Set an EV charger's ampere setpoint (variable-current control).

        Args:
            entity_id: HA number entity controlling charge current (A)
            amps: Target ampere setpoint

        Returns:
            ActionResult with details of the action
        """
        start = time.time()

        current_state = await self.ha.get_state_value(entity_id)

        # Idempotent skip
        if self._values_match(current_state, amps):
            return ActionResult(
                action_type="ev_charge_current",
                success=True,
                message=f"EV charger current already {amps}A",
                previous_value=current_state,
                new_value=amps,
                entity_id=entity_id,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
                error_details=None,
            )

        if self.shadow_mode:
            logger.info(
                "[SHADOW] EV Charger: Would set current to %sA (current: %s)",
                amps,
                current_state,
            )
            return ActionResult(
                action_type="ev_charge_current",
                success=True,
                message=f"[SHADOW] Would change {current_state} -> {amps}A",
                previous_value=current_state,
                new_value=amps,
                entity_id=entity_id,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
                error_details=None,
            )

        error_details = None
        try:
            await self.ha.set_number(entity_id, float(amps))
            success = True
        except HACallError as e:
            success = False
            error_details = str(e)
            logger.error("Failed to set EV charger current %s: %s", entity_id, error_details)

        # Verification
        verified_value = None
        verification_success = None
        if success:
            verified_value, verification_success = await self._verify_action(entity_id, amps)

        duration = int((time.time() - start) * 1000)

        return ActionResult(
            action_type="ev_charge_current",
            success=success,
            message=(
                f"EV charger current set to {amps}A"
                if success
                else f"Failed: {error_details}"
                if error_details
                else "Failed to set EV charger current"
            ),
            previous_value=current_state,
            new_value=amps,
            entity_id=entity_id,
            verified_value=verified_value,
            verification_success=verification_success,
            duration_ms=duration,
            error_details=error_details,
        )

    async def set_ev_phase_mode(self, entity_id: str, mode: int) -> ActionResult:
        """
        Command an EV charger's phase mode (1 or 3-phase) via its HA select entity.

        Args:
            entity_id: HA select entity controlling commanded phase mode
            mode: 1 or 3 (phase count)

        Returns:
            ActionResult with details of the action
        """
        start = time.time()
        option = str(mode)

        current_state = await self.ha.get_state_value(entity_id)

        # Idempotent skip
        if self._values_match(current_state, option):
            return ActionResult(
                action_type="ev_phase_mode",
                success=True,
                message=f"EV charger phase mode already {option}",
                previous_value=current_state,
                new_value=option,
                entity_id=entity_id,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
                error_details=None,
            )

        if self.shadow_mode:
            logger.info(
                "[SHADOW] EV Charger: Would set phase mode to %s (current: %s)",
                option,
                current_state,
            )
            return ActionResult(
                action_type="ev_phase_mode",
                success=True,
                message=f"[SHADOW] Would change {current_state} -> {option}",
                previous_value=current_state,
                new_value=option,
                entity_id=entity_id,
                skipped=True,
                duration_ms=int((time.time() - start) * 1000),
                error_details=None,
            )

        error_details = None
        try:
            await self.ha.set_select_option(entity_id, option)
            success = True
        except HACallError as e:
            success = False
            error_details = str(e)
            logger.error("Failed to set EV charger phase mode %s: %s", entity_id, error_details)

        # Read-back verification
        verified_value = None
        verification_success = None
        if success:
            verified_value, verification_success = await self._verify_action(entity_id, option)

        duration = int((time.time() - start) * 1000)

        return ActionResult(
            action_type="ev_phase_mode",
            success=success,
            message=(
                f"EV charger phase mode set to {option}"
                if success
                else f"Failed: {error_details}"
                if error_details
                else "Failed to set EV charger phase mode"
            ),
            previous_value=current_state,
            new_value=option,
            entity_id=entity_id,
            verified_value=verified_value,
            verification_success=verification_success,
            duration_ms=duration,
            error_details=error_details,
        )

    async def _maybe_notify(self, action_type: str, message: str) -> None:
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
            await self._send_notification(message)

    async def _send_notification(self, message: str, title: str = "Darkstar Executor") -> None:
        """Send a notification via the configured service."""
        if self.shadow_mode:
            logger.info("[SHADOW] Would send notification: %s", message)
            return

        try:
            await self.ha.send_notification(
                self.config.notifications.service,
                title,
                message,
            )
        except Exception as e:
            logger.warning("Failed to send notification: %s", e)

    async def notify_balancer_intervention(self, message: str) -> None:
        """Balancer intervention notification (load-balancing-completion 5.1).

        HA notify via the configured service first; falls back to the Discord
        webhook from secrets.yaml when HA delivery fails or no service is set.
        Gating (notify_interventions, once per transition) is the engine's job.
        """
        title = "Darkstar Load Balancer"
        if self.shadow_mode:
            logger.info("[SHADOW] Would send balancer notification: %s", message)
            return

        sent = False
        try:
            sent = await self.ha.send_notification(
                self.config.notifications.service, title, message
            )
        except Exception as e:
            logger.warning("Balancer HA notification failed: %s", e)

        if not sent:
            try:
                from backend.core.secrets import load_notifications_config
                from backend.notify import send_critical_notification

                webhook = load_notifications_config().get("discord_webhook_url")
                if webhook:
                    await asyncio.to_thread(
                        send_critical_notification,
                        title,
                        message,
                        discord_webhook_url=webhook,
                    )
                else:
                    logger.warning(
                        "Balancer notification undeliverable (no HA service, "
                        "no Discord webhook): %s",
                        message,
                    )
            except Exception as e:
                logger.warning("Balancer Discord fallback failed: %s", e)

    async def notify_override(self, override_type: str, reason: str) -> None:
        """Send notification about an override activation."""
        if self.config.notifications.on_override_activated:
            await self._send_notification(
                f"Override: {override_type}\n{reason}",
                title="Darkstar Override Active",
            )

    async def notify_error(self, error: str) -> None:
        """Send notification about an error."""
        if self.config.notifications.on_error:
            await self._send_notification(
                f"Error: {error}",
                title="Darkstar Executor Error",
            )
