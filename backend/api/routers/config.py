from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from typing import Dict, Any
import os
import yaml
from inputs import _load_yaml, load_home_assistant_config, load_notification_secrets

router = APIRouter(tags=["config"])

@router.get("/api/config")
async def get_config():
    """Get sanitized config."""
    try:
        conf = _load_yaml("config.yaml") or {}
        
        # Merge Home Assistant secrets
        ha_secrets = load_home_assistant_config()
        if ha_secrets:
            if "home_assistant" not in conf:
                conf["home_assistant"] = {}
            # Update only keys that exist in secrets (overwriting config.yaml placeholders)
            conf["home_assistant"].update(ha_secrets)

        # Merge Notification secrets
        notif_secrets = load_notification_secrets()
        if notif_secrets:
            if "notifications" not in conf:
                conf["notifications"] = {}
            conf["notifications"].update(notif_secrets)

        # Sanitize secrets before returning
        if "home_assistant" in conf:
            conf["home_assistant"].pop("token", None)
        if "notifications" in conf:
            for key in ["api_key", "token", "password", "webhook_url"]:
                conf.get("notifications", {}).pop(key, None)

        return conf
    except Exception as e:
        return {"error": str(e)}

@router.post("/api/config/save")
async def save_config(payload: Dict[str, Any] = Body(...)):
    """Save config.yaml."""
    try:
        from ruamel.yaml import YAML
        yaml_handler = YAML()
        yaml_handler.preserve_quotes = True
        
        # We might want to merge payload into existing to preserve comments?
        # Or just dump. webapp.py usually did a load-update-dump cycle using ruamel.
        with open("config.yaml", "r", encoding="utf-8") as f:
            data = yaml_handler.load(f) or {}

        # Recursive update or specific sections?
        # webapp.py usually replaced specific sections or the whole thing.
        # Let's assume payload is the full config or specific keys?
        # webapp.py implementation:
        # data.update(payload) basically.
        
        # Deep merge helper
        def deep_update(source, overrides):
             for key, value in overrides.items():
                 if isinstance(value, dict) and value:
                     returned = deep_update(source.get(key, {}), value)
                     source[key] = returned
                 else:
                     source[key] = overrides[key]
             return source

        deep_update(data, payload)

        with open("config.yaml", "w", encoding="utf-8") as f:
            yaml_handler.dump(data, f)
            
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.post("/api/config/reset")
async def reset_config():
    """Reset to default config."""
    if os.path.exists("config.default.yaml"):
        import shutil
        shutil.copy("config.default.yaml", "config.yaml")
        return {"status": "success"}
    return {"status": "error", "message": "Default config not found"}
