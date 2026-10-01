"""Readiness diagnostics and fresh planning without schedule or hardware publication."""

import asyncio
import copy
import math
from typing import Any

from backend.core.entity_matcher import value_at_path
from backend.core.entity_roles import POWER_UNITS
from backend.core.ha_registry import discover_entities
from backend.core.secrets import load_home_assistant_config, load_yaml
from backend.health import HealthChecker
from planner.preflight import check_battery_config

PLAN_TIMEOUT_SECONDS = 60


async def run_isolated_plan(config: dict[str, Any]) -> int:
    """Calculate a new result independently of the live planner service."""
    from backend.core.forecasts import get_all_input_data
    from planner.pipeline import generate_schedule

    inputs = await get_all_input_data()
    result = await generate_schedule(
        inputs, config=copy.deepcopy(config), save_to_file=False, publish_state=False
    )
    return len(result)


async def check_readiness(config: dict[str, Any]) -> dict[str, Any]:
    from backend.api.routers.config import _validate_config_for_save  # type: ignore[import-private]
    from backend.core.prices import get_nordpool_data
    from executor.actions import _STANDARD_INVERTER_KEYS  # type: ignore[import-private]
    from executor.profiles import get_profile_from_config

    checks: list[dict[str, Any]] = []
    system = config.get("system", {})

    def add(
        check_id: str, group: str, status: str, message: str, path: str, hint: str = ""
    ) -> None:
        checks.append(
            {
                "id": check_id,
                "group": group,
                "status": status,
                "message": message,
                "fix_hint": hint or ("Review this setting." if status in ("fail", "warn") else ""),
                "settings_path": path,
            }
        )

    credentials = load_home_assistant_config()
    if not credentials.get("url") or not credentials.get("token"):
        add(
            "ha_connection",
            "connection",
            "fail",
            "HA is not configured.",
            "home_assistant",
            "Set the Home Assistant URL and token.",
        )
    else:
        issues = await HealthChecker().check_ha_connection(credentials)
        add(
            "ha_connection",
            "connection",
            "fail" if issues else "pass",
            issues[0].message if issues else "Home Assistant is reachable.",
            "home_assistant",
            issues[0].guidance if issues else "",
        )
    try:
        discovery = await discover_entities()
        states = {entity["entity_id"]: entity for entity in discovery["entities"]}
    except Exception:
        states = {}
        add("ha_discovery", "connection", "fail", "Cannot read live HA entities.", "home_assistant")

    dual = system.get("grid_meter_type", "net") == "dual"
    sensor_flags = {
        "load_power": True,
        "battery_soc": system.get("has_battery", True),
        "battery_power": system.get("has_battery", True),
        "pv_power": system.get("has_solar", True),
        "grid_power": not dual,
        "grid_import_power": dual,
        "grid_export_power": dual,
    }
    for role, enabled in sensor_flags.items():
        path = f"input_sensors.{role}"
        if not enabled:
            add(role, "sensors", "skipped", "Not used by this system.", path)
            continue
        entity = states.get(value_at_path(config, path))
        if entity is None:
            add(
                role,
                "sensors",
                "fail",
                f"{role}: entity missing.",
                path,
                "Choose an existing HA sensor.",
            )
            continue
        try:
            value = float(entity.get("state"))
            if not math.isfinite(value):
                raise ValueError("Non-finite sensor value")
        except (ValueError, TypeError):
            add(role, "sensors", "fail", f"{role}: live state is unavailable or non-numeric.", path)
            continue
        unit = entity.get("unit_of_measurement")
        plausible = (
            unit == "%" and 0 <= value <= 100 if role == "battery_soc" else unit in POWER_UNITS
        )
        if (
            role in ("pv_power", "load_power", "grid_import_power", "grid_export_power")
            and value < 0
        ):
            plausible = False
        add(
            role,
            "sensors",
            "pass" if plausible else "warn",
            f"{role}: {value} {unit or '(no unit)'}.",
            path,
            "Choose a sensor with a plausible live value and the expected unit (% or W/kW).",
        )

    if system.get("has_battery", True):
        try:
            check_battery_config(config)
            add("battery_limits", "battery", "pass", "Battery limits are valid.", "battery")
        except (ValueError, TypeError, ArithmeticError) as exc:
            add("battery_limits", "battery", "fail", str(exc), "battery")
        except Exception as exc:
            add(
                "battery_limits",
                "battery",
                "fail",
                str(exc),
                "battery",
                "Set capacity, positive charge/discharge Watts and min SoC below max SoC.",
            )
        try:
            profile = get_profile_from_config(config)
            for key, definition in profile.get_required_entities().items():
                path = (
                    f"executor.inverter.{key}"
                    if key in _STANDARD_INVERTER_KEYS
                    else f"executor.inverter.custom_entities.{key}"
                )
                custom = (
                    config.get("executor", {})
                    .get("inverter", {})
                    .get("custom_entities", {})
                    .get(key)
                )
                eid = custom or value_at_path(config, path) or definition.default_entity
                add(
                    f"profile_{key}",
                    "profile",
                    "pass" if eid in states else "fail",
                    f"{key}: " + ("entity exists." if eid in states else "entity missing."),
                    path,
                )
        except Exception as exc:
            add("profile", "profile", "fail", str(exc), "system.inverter_profile")
    else:
        add("battery_limits", "battery", "skipped", "Battery disabled.", "battery")
        add("profile", "profile", "skipped", "Battery disabled.", "system.inverter_profile")

    solar = system.get("has_solar", True)
    if solar:
        try:
            arrays = system.get("solar_arrays", []) or [system.get("solar_array", {})]
            valid = bool(arrays) and all(
                math.isfinite(float(a.get("kwp", 0))) and float(a.get("kwp", 0)) > 0 for a in arrays
            )
        except (ValueError, TypeError):
            valid = False
        add(
            "pv_arrays",
            "solar",
            "pass" if valid else "fail",
            "PV arrays have positive kWp." if valid else "Set positive kWp for each PV array.",
            "system.solar_arrays",
        )
        location = system.get("location", {})
        default_location = load_yaml("config.default.yaml").get("system", {}).get("location", {})
        try:
            lat, lon = float(location["latitude"]), float(location["longitude"])
            valid_location = (
                math.isfinite(lat)
                and math.isfinite(lon)
                and -90 <= lat <= 90
                and -180 <= lon <= 180
                and (lat, lon)
                != (
                    float(default_location.get("latitude", 0)),
                    float(default_location.get("longitude", 0)),
                )
            )
        except (KeyError, ValueError, TypeError):
            valid_location = False
        add(
            "location",
            "solar",
            "pass" if valid_location else "fail",
            "Location configured."
            if valid_location
            else "Location is missing, invalid or still the shipped placeholder.",
            "system.location",
        )
    else:
        for name in ("pv_arrays", "location"):
            add(
                name,
                "solar",
                "skipped",
                "Solar disabled.",
                f"system.{'solar_arrays' if name == 'pv_arrays' else name}",
            )

    for flag, section, group in (
        ("has_water_heater", "water_heaters", "water_heater"),
        ("has_ev_charger", "ev_chargers", "ev"),
    ):
        if not system.get(flag, group == "water_heater"):
            add(group, group, "skipped", "Feature disabled.", section)
            continue
        scoped = copy.deepcopy(config)
        scoped["system"] = {
            **system,
            "has_battery": False,
            "has_solar": False,
            "has_water_heater": flag == "has_water_heater",
            "has_ev_charger": flag == "has_ev_charger",
        }
        issues = _validate_config_for_save(scoped)
        # Save validation includes unrelated pricing/grid rules; retain this feature's issues.
        words = (
            ("water heater", "water_heater", "water heating")
            if group == "water_heater"
            else ("ev ", "ev_", "charger")
        )
        relevant = [i for i in issues if any(word in i["message"].lower() for word in words)]
        entries = [(i, e) for i, e in enumerate(config.get(section, [])) if e.get("enabled", True)]
        failures = [i["message"] for i in relevant if i.get("severity") == "error"]
        if not entries:
            failures.append("Configure at least one enabled device.")
        add(
            group,
            group,
            "fail" if failures else "pass",
            "; ".join(failures) if failures else "Device configuration is valid.",
            section,
        )
        for index, entry in entries:
            required = (
                ["target_entity"]
                if group == "water_heater"
                else ["switch_entity", "soc_sensor", "plug_sensor"]
                + (["current_entity"] if entry.get("type") == "current" else [])
            )
            fields = set(required) | {"sensor"}
            if group == "ev":
                fields |= {
                    "phase_sensor_l1",
                    "phase_sensor_l2",
                    "phase_sensor_l3",
                    "phase_mode_entity",
                    "ha_ready_by_entity",
                    "ha_target_soc_entity",
                }
            for field in sorted(fields):
                eid = entry.get(field)
                if not eid and field not in required:
                    continue
                path = f"{section}.{index}.{field}"
                add(
                    f"{group}_{index}_{field}",
                    group,
                    "pass" if eid in states else "fail",
                    f"{field}: " + ("entity exists." if eid in states else "entity missing."),
                    path,
                )
    try:
        prices = await get_nordpool_data()
        add(
            "prices",
            "pricing",
            "pass" if prices else "fail",
            f"{len(prices)} Nordpool slots available.",
            "pricing.price_area",
        )
    except Exception:
        add("prices", "pricing", "fail", "Nordpool prices unavailable.", "pricing.price_area")
    try:
        slots = await asyncio.wait_for(run_isolated_plan(config), timeout=PLAN_TIMEOUT_SECONDS)
        add(
            "plan",
            "planner",
            "pass" if slots > 0 else "fail",
            f"Fresh test plan produced {slots} slots.",
            "automation",
        )
    except TimeoutError:
        add(
            "plan",
            "planner",
            "warn",
            "Test planning timed out.",
            "automation",
            "Retry readiness once input services respond.",
        )
    except Exception as exc:
        add("plan", "planner", "fail", f"Test planning failed: {exc}", "automation")
    return {"ready": not any(c["status"] == "fail" for c in checks), "checks": checks}
