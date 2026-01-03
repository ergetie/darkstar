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
async def save_config(payload: dict[str, Any] = Body(...)) -> dict[str, str]:
    """Save config.yaml."""
    try:
        yaml_handler = YAML()
        yaml_handler.preserve_quotes = True

        # We might want to merge payload into existing to preserve comments?
        # Or just dump. webapp.py usually did a load-update-dump cycle using ruamel.
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
            deep_update(data, payload)

        with config_path.open("w", encoding="utf-8") as f:
            yaml_handler.dump(data, f)  # type: ignore

        return {"status": "success"}
    except Exception as e:
        raise HTTPException(500, str(e)) from e


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
