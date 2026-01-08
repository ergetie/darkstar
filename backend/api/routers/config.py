import logging
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Body, HTTPException
from ruamel.yaml import YAML

from inputs import load_home_assistant_config, load_notifications_config, load_yaml

logger = logging.getLogger("darkstar.api.config")

router = APIRouter(tags=["config"])


@router.get(
    "/api/config",
    summary="Get System Configuration",
    description="Returns sanitized configuration with secrets redacted.",
)
async def get_config() -> dict[str, Any]:
    """Get sanitized config."""
    try:
        conf: dict[str, Any] = load_yaml("config.yaml") or {}

        # Merge Home Assistant secrets
        ha_secrets = load_home_assistant_config()
        if ha_secrets:
            if "home_assistant" not in conf:
                conf["home_assistant"] = {}
            # Update only keys that exist in secrets (overwriting config.yaml placeholders)
            cast("dict[str, Any]", conf["home_assistant"]).update(ha_secrets)

        # Merge Notification secrets
        notif_secrets = load_notifications_config()
        if notif_secrets:
            if "notifications" not in conf:
                conf["notifications"] = {}
            cast("dict[str, Any]", conf["notifications"]).update(notif_secrets)

        # Sanitize secrets before returning
        if "home_assistant" in conf:
            cast("dict[str, Any]", conf["home_assistant"]).pop("token", None)
        if "notifications" in conf:
            for key in ["api_key", "token", "password", "webhook_url"]:
                cast("dict[str, Any]", conf.get("notifications", {})).pop(key, None)

        return conf
    except Exception as e:
        return {"error": str(e)}


@router.post(
    "/api/config/save",
    summary="Save Configuration",
    description="Updates config.yaml with new values.",
)
async def save_config(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Save config.yaml."""
    try:
        yaml_handler = YAML()
        yaml_handler.preserve_quotes = True

        # We might want to merge payload into existing to preserve comments?
        # Or just dump. webapp.py usually did a load-update-dump cycle using ruamel.
        # EXCLUSION FILTER: Ensure secrets from secrets.yaml never leak into config.yaml
        # These keys should only live in secrets.yaml
        SECRET_KEYS = {
            "home_assistant": {"token", "url"},
            "notifications": {"api_key", "token", "password", "webhook_url", "discord_webhook_url"},
            "openrouter_api_key": None,
        }

        def filter_secrets(overrides: dict[str, Any], exclusions: dict[str, Any] | None) -> None:
            """Recursively remove keys that are marked as secrets from the payload."""
            if exclusions is None:
                return

            for key in list(overrides.keys()):
                if key in exclusions:
                    excl_val = exclusions[key]
                    if excl_val is None:
                        logger.warning(f"Security: Stripped sensitive block '{key}' from config save.")
                        overrides.pop(key)
                    elif isinstance(overrides[key], dict):
                        if isinstance(excl_val, set):
                            for subkey in list(overrides[key].keys()):
                                if subkey in excl_val:
                                    logger.warning(f"Security: Stripped sensitive sub-key '{key}.{subkey}' from config save.")
                                    overrides[key].pop(subkey)
                        elif isinstance(excl_val, dict):
                            filter_secrets(overrides[key], excl_val)

                        if not overrides[key]:
                            overrides.pop(key)

        # Deep merge helper
        def deep_update(source: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
            for key, value in overrides.items():
                if isinstance(value, dict) and value:
                    returned = deep_update(
                        cast("dict[str, Any]", source.get(key, {})), cast("dict[str, Any]", value)
                    )
                    source[key] = returned
                else:
                    source[key] = overrides[key]
            return source

        config_path = Path("config.yaml")
        with config_path.open(encoding="utf-8") as f:
            data = cast("dict[str, Any]", yaml_handler.load(f) or {})  # type: ignore

            # Filter the incoming payload before merging
            filter_secrets(payload, SECRET_KEYS)

            deep_update(data, payload)

        # REV LCL01: Validate config before saving and collect warnings/errors
        validation_issues = _validate_config_for_save(data)
        errors = [i for i in validation_issues if i["severity"] == "error"]
        warnings = [i for i in validation_issues if i["severity"] == "warning"]

        # If there are critical errors, reject the save
        if errors:
            raise HTTPException(
                400,
                detail={
                    "message": "Configuration has critical errors",
                    "errors": errors,
                    "warnings": warnings,
                },
            )

        # Save the config (even if warnings exist)
        with config_path.open("w", encoding="utf-8") as f:
            yaml_handler.dump(data, f)  # type: ignore

        # Return success with any warnings
        if warnings:
            return {"status": "success", "warnings": warnings}  # type: ignore[return-value]
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e)) from e


def _validate_config_for_save(config: dict[str, Any]) -> list[dict[str, str]]:
    """Validate config and return list of issues.

    REV LCL01: Run on every config save to catch misconfigurations immediately.
    Returns list of {"severity": "error"|"warning", "message": str, "guidance": str}
    """
    issues: list[dict[str, str]] = []
    system_cfg = config.get("system", {})
    water_cfg = config.get("water_heating", {})
    battery_cfg = config.get("battery", {})

    # Battery: ERROR if enabled but no capacity (breaks MILP solver)
    if system_cfg.get("has_battery", True):
        try:
            capacity = float(battery_cfg.get("capacity_kwh", 0) or 0)
        except (ValueError, TypeError):
            capacity = 0.0
        if capacity <= 0:
            issues.append({
                "severity": "error",
                "message": "Battery enabled but capacity not configured",
                "guidance": "Set battery.capacity_kwh to your battery's capacity, "
                "or set system.has_battery to false.",
            })

    # Water heater: WARNING (feature disabled, system still works)
    if system_cfg.get("has_water_heater", True):
        try:
            power_kw = float(water_cfg.get("power_kw", 0) or 0)
        except (ValueError, TypeError):
            power_kw = 0.0
        if power_kw <= 0:
            issues.append({
                "severity": "warning",
                "message": "Water heater enabled but power not configured",
                "guidance": "Set water_heating.power_kw to your heater's power (e.g., 3.0), "
                "or set system.has_water_heater to false.",
            })

    # Solar: WARNING (PV forecasts will be zero)
    if system_cfg.get("has_solar", True):
        solar_cfg = system_cfg.get("solar_array", {})
        try:
            kwp = float(solar_cfg.get("kwp", 0) or 0)
        except (ValueError, TypeError):
            kwp = 0.0
        if kwp <= 0:
            issues.append({
                "severity": "warning",
                "message": "Solar enabled but panel size not configured",
                "guidance": "Set system.solar_array.kwp to your PV capacity, "
                "or set system.has_solar to false.",
            })

    return issues


@router.post(
    "/api/config/reset",
    summary="Reset Configuration",
    description="Resets config.yaml to defaults.",
)
async def reset_config() -> dict[str, str]:
    """Reset to default config."""
    default_cfg = Path("config.default.yaml")
    if default_cfg.exists():
        import shutil

        shutil.copy(str(default_cfg), "config.yaml")
        return {"status": "success"}
    return {"status": "error", "message": "Default config not found"}
