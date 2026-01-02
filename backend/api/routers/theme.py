from fastapi import APIRouter, HTTPException, Body
from typing import Optional, List, Dict
from pydantic import BaseModel
import yaml
import os
import json
import logging

logger = logging.getLogger("darkstar.api.theme")
router = APIRouter(tags=["theme"])

THEME_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "themes")

class ThemeSelectRequest(BaseModel):
    theme: str
    accent_index: Optional[int] = None

# Helper functions (ported from webapp.py)
def _parse_legacy_theme_format(text: str) -> dict:
    """Parse simple key/value themes."""
    palette = [None] * 16
    data = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            continue
        key, value = key.strip(), value.strip()
        if key.lower() == "palette":
            if "=" in value:
                idx_str, color = value.split("=", 1)
                idx = int(idx_str.strip())
                color = color.strip()
            else:
                try:
                    idx = palette.index(None)
                except ValueError as exc:
                    raise ValueError("Too many palette entries") from exc
                color = value
            if idx < 0 or idx > 15:
                raise ValueError(f"Palette index {idx} out of range 0-15")
            palette[idx] = color
        else:
            data[key.lower().replace("-", "_")] = value
    if any(swatch is None for swatch in palette):
        raise ValueError("Palette must define 16 colours")
    data["palette"] = palette
    return data

def _normalise_theme(name: str, raw_data: dict) -> dict:
    if not isinstance(raw_data, dict):
        raise ValueError("Theme data must be a mapping")
    palette = raw_data.get("palette")
    if not isinstance(palette, (list, tuple)) or len(palette) != 16:
        raise ValueError("Palette must contain exactly 16 colours")
    def _clean_colour(value, key):
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        value = value.strip()
        if not value.startswith("#"):
            raise ValueError(f"{key} must be a hex colour starting with #")
        return value
    return {
        "name": name,
        "foreground": _clean_colour(raw_data.get("foreground", "#ffffff"), "foreground"),
        "background": _clean_colour(raw_data.get("background", "#000000"), "background"),
        "palette": [_clean_colour(c, f"palette[{i}]") for i, c in enumerate(palette)],
    }

def _load_theme_file(path: str) -> dict:
    with open(path, "r") as handle:
        text = handle.read()
    filename = os.path.basename(path)
    try:
        if filename.lower().endswith(".json"):
            raw_data = json.loads(text)
        elif filename.lower().endswith((".yaml", ".yml")):
            raw_data = yaml.safe_load(text)
        else:
            raw_data = _parse_legacy_theme_format(text)
    except Exception as exc:
        raise ValueError(f"Failed to parse theme '{filename}': {exc}") from exc
    return _normalise_theme(os.path.splitext(filename)[0] or filename, raw_data)

def load_themes(theme_dir: str = THEME_DIR) -> dict:
    themes = {}
    if not os.path.isdir(theme_dir):
        return themes
    for entry in sorted(os.listdir(theme_dir)):
        path = os.path.join(theme_dir, entry)
        if not os.path.isfile(path):
            continue
        try:
            theme = _load_theme_file(path)
            themes[theme["name"]] = theme
        except Exception as exc:
            logger.warning("Skipping theme '%s': %s", entry, exc)
            continue
    return themes

AVAILABLE_THEMES = {}

@router.get("/api/themes")
async def list_themes():
    """Return all available themes and the currently selected theme."""
    global AVAILABLE_THEMES
    AVAILABLE_THEMES = load_themes()
    
    current_name = None
    accent_index = None
    try:
        with open("config.yaml", "r") as handle:
            config = yaml.safe_load(handle) or {}
            ui = config.get("ui", {})
            current_name = ui.get("theme")
            accent_index = ui.get("theme_accent_index")
    except FileNotFoundError:
        pass

    if current_name not in AVAILABLE_THEMES:
        current_name = next(iter(AVAILABLE_THEMES.keys()), None)

    return {
        "current": current_name,
        "accent_index": accent_index,
        "themes": list(AVAILABLE_THEMES.values()),
    }

@router.post("/api/theme")
async def select_theme(payload: ThemeSelectRequest):
    """Persist a selected theme to config.yaml."""
    global AVAILABLE_THEMES
    AVAILABLE_THEMES = load_themes() # Reload to be sure

    if payload.theme not in AVAILABLE_THEMES:
        raise HTTPException(status_code=404, detail=f"Theme '{payload.theme}' not found")
    
    if payload.accent_index is not None and not (0 <= payload.accent_index <= 15):
        raise HTTPException(status_code=400, detail="accent_index must be between 0 and 15")

    try:
        from ruamel.yaml import YAML
        yaml_handler = YAML()
        yaml_handler.preserve_quotes = True
        with open("config.yaml", "r", encoding="utf-8") as handle:
            config = yaml_handler.load(handle) or {}
    except FileNotFoundError:
        config = {}

    ui_section = config.setdefault("ui", {})
    ui_section["theme"] = payload.theme
    if payload.accent_index is not None:
        ui_section["theme_accent_index"] = payload.accent_index

    with open("config.yaml", "w", encoding="utf-8") as handle:
        yaml_handler.dump(config, handle)

    return {
        "status": "success",
        "current": payload.theme,
        "accent_index": payload.accent_index,
        "theme": AVAILABLE_THEMES[payload.theme],
    }
