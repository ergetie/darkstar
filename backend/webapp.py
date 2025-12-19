import json
import logging
import os
import shutil
import sqlite3
import threading
import sys
from collections import deque
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytz
import yaml
from flask import Flask, jsonify, render_template, request, send_from_directory
import pymysql
import subprocess

from planner.pipeline import PlannerPipeline
from planner.simulation import simulate_schedule
from planner.inputs.data_prep import prepare_df
from planner.output.formatter import dataframe_to_json_response
from planner.strategy.manual_plan import apply_manual_plan
from db_writer import write_schedule_to_db
from inputs import (
    _load_yaml,
    get_all_input_data,
    _get_load_profile_from_ha,
    get_home_assistant_sensor_float,
    load_home_assistant_config,
)
from backend.learning import get_learning_engine
from backend.strategy.engine import StrategyEngine
from backend.strategy.analyst import EnergyAnalyst
from backend.strategy.voice import get_advice
from backend.api.aurora import aurora_bp

app = Flask(__name__)
app.register_blueprint(aurora_bp)

THEME_DIR = os.path.join(os.path.dirname(__file__), "themes")


# --- Static Asset Handling ---
@app.route("/assets/<path:path>")
def send_assets(path):
    # Serve assets from the 'static/assets' folder
    directory = os.path.join(os.path.dirname(__file__), "static", "assets")
    return send_from_directory(directory, path)


@app.route("/favicon.svg")
def send_favicon():
    return send_from_directory("static", "favicon.svg")


# --- SPA Catch-All ---
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def index(path):
    # Let Flask handle static/api routes, others fall through to React
    if path.startswith("api/") or path.startswith("static/") or path.startswith("assets/"):
        return "Not Found", 404
    return render_template("index.html")


class RingBufferHandler(logging.Handler):
    """In-memory ring buffer for log entries that the UI can poll."""

    def __init__(self, maxlen: int = 1000):
        super().__init__()
        self._buffer = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc)
        except Exception:
            timestamp = datetime.now(timezone.utc)
        entry = {
            "timestamp": timestamp.isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self.format(record),
        }
        self._buffer.append(entry)

    def get_logs(self) -> list:
        return list(self._buffer)


_ring_buffer_handler = RingBufferHandler(maxlen=1000)
_ring_buffer_formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
_ring_buffer_handler.setFormatter(_ring_buffer_formatter)

logger = logging.getLogger("darkstar.webapp")
logger.setLevel(logging.INFO)
if not any(isinstance(h, RingBufferHandler) for h in logger.handlers):
    logger.addHandler(_ring_buffer_handler)
logger.propagate = False

_advice_cache = {"planned_at": None, "text": None}


def _get_git_version() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "describe", "--tags", "--always", "--dirty"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except Exception:
        return "dev"


def _parse_legacy_theme_format(text: str) -> dict:
    """Parse simple key/value themes with `palette = index=#hex` lines."""
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

        key = key.strip()
        value = value.strip()

        if key.lower() == "palette":
            if "=" in value:
                idx_str, color = value.split("=", 1)
                idx = int(idx_str.strip())
                color = color.strip()
            else:
                # Allow sequential palette entries without explicit index.
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
        raise ValueError("Palette must define 16 colours (indices 0-15)")

    data["palette"] = palette
    return data


def _normalise_theme(name: str, raw_data: dict) -> dict:
    """Ensure theme dictionaries contain the expected keys."""
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

    palette = [_clean_colour(colour, f"palette[{idx}]") for idx, colour in enumerate(palette)]
    foreground = _clean_colour(raw_data.get("foreground", "#ffffff"), "foreground")
    background = _clean_colour(raw_data.get("background", "#000000"), "background")

    return {
        "name": name,
        "foreground": foreground,
        "background": background,
        "palette": palette,
    }


def _load_theme_file(path: str) -> dict:
    """Load a single theme file supporting JSON, YAML, and legacy key/value formats."""
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
    """Scan the themes directory and load all available themes."""
    themes = {}
    if not os.path.isdir(theme_dir):
        return themes

    for entry in sorted(os.listdir(theme_dir)):
        path = os.path.join(theme_dir, entry)
        if not os.path.isfile(path):
            continue
        try:
            theme = _load_theme_file(path)
        except Exception as exc:
            # Skip invalid themes but log for operator visibility.
            logger.warning("Skipping theme '%s': %s", entry, exc)
            continue
        themes[theme["name"]] = theme
    return themes


AVAILABLE_THEMES = load_themes()


def get_current_theme_name() -> str:
    """Return the theme stored in config.yaml if available."""
    try:
        with open("config.yaml", "r") as handle:
            config = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        config = {}
    ui_section = config.get("ui", {})
    selected = ui_section.get("theme")
    if selected in AVAILABLE_THEMES:
        return selected
    return next(iter(AVAILABLE_THEMES.keys()), None)


@app.route("/api/themes", methods=["GET"])
def list_themes():
    """Return all available themes and the currently selected theme."""
    global AVAILABLE_THEMES
    AVAILABLE_THEMES = load_themes()
    current_name = get_current_theme_name()
    accent_index = None
    try:
        with open("config.yaml", "r") as handle:
            config = yaml.safe_load(handle) or {}
            accent_index = config.get("ui", {}).get("theme_accent_index")
    except FileNotFoundError:
        pass
    try:
        accent_index = int(accent_index)
    except (TypeError, ValueError):
        accent_index = None
    return jsonify(
        {
            "current": current_name,
            "accent_index": accent_index,
            "themes": list(AVAILABLE_THEMES.values()),
        }
    )


@app.route("/api/forecast/eval", methods=["GET"])
def forecast_eval():
    """Return simple MAE metrics for baseline vs AURORA forecasts over recent days."""
    try:
        engine = get_learning_engine()
        days_back = int(request.args.get("days", "7"))
    except Exception:
        days_back = 7

    now = datetime.now(timezone.utc)
    start_time = now - timedelta(days=max(days_back, 1))

    with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
        cursor = conn.cursor()
        rows = cursor.execute(
            """
            SELECT
                f.forecast_version,
                AVG(ABS(o.pv_kwh - f.pv_forecast_kwh)) as mae_pv,
                AVG(ABS(o.load_kwh - f.load_forecast_kwh)) as mae_load,
                COUNT(*) as samples
            FROM slot_observations o
            JOIN slot_forecasts f
              ON o.slot_start = f.slot_start
            WHERE o.slot_start >= ? AND o.slot_start < ?
              AND f.forecast_version IN ('baseline_7_day_avg', 'aurora')
            GROUP BY f.forecast_version
            """,
            (start_time.isoformat(), now.isoformat()),
        ).fetchall()

    versions = []
    for version, mae_pv, mae_load, samples in rows:
        versions.append(
            {
                "version": version,
                "mae_pv": None if mae_pv is None else float(mae_pv),
                "mae_load": None if mae_load is None else float(mae_load),
                "samples": int(samples or 0),
            }
        )

    return jsonify(
        {
            "window": {"start": start_time.isoformat(), "end": now.isoformat()},
            "versions": versions,
        }
    )


@app.route("/api/forecast/day", methods=["GET"])
def forecast_day():
    """Return per-slot actual vs baseline/AURORA forecasts for a single day."""
    engine = get_learning_engine()
    tz_name = engine.timezone.zone if hasattr(engine.timezone, "zone") else "Europe/Stockholm"
    tz = pytz.timezone(tz_name)

    date_param = request.args.get("date")
    try:
        target_date = (
            datetime.fromisoformat(date_param).date() if date_param else datetime.now(tz).date()
        )
    except Exception:
        target_date = datetime.now(tz).date()

    day_start = tz.localize(datetime(target_date.year, target_date.month, target_date.day))
    day_end = day_start + timedelta(days=1)

    with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
        cursor = conn.cursor()
        obs_rows = cursor.execute(
            """
            SELECT slot_start, pv_kwh, load_kwh
            FROM slot_observations
            WHERE slot_start >= ? AND slot_start < ?
            ORDER BY slot_start ASC
            """,
            (day_start.isoformat(), day_end.isoformat()),
        ).fetchall()

        f_rows = cursor.execute(
            """
            SELECT slot_start, pv_forecast_kwh, load_forecast_kwh, forecast_version,
                   pv_p10, pv_p90, load_p10, load_p90
            FROM slot_forecasts
            WHERE slot_start >= ? AND slot_start < ?
              AND forecast_version IN ('baseline_7_day_avg', 'aurora')
            """,
            (day_start.isoformat(), day_end.isoformat()),
        ).fetchall()

    df_obs = pd.DataFrame(obs_rows, columns=["slot_start", "pv_kwh", "load_kwh"])
    df_f = pd.DataFrame(
        f_rows,
        columns=[
            "slot_start",
            "pv_forecast_kwh",
            "load_forecast_kwh",
            "forecast_version",
            "pv_p10",
            "pv_p90",
            "load_p10",
            "load_p90",
        ],
    )
    if df_obs.empty:
        return jsonify({"date": target_date.isoformat(), "slots": []})

    df_obs["slot_start"] = pd.to_datetime(df_obs["slot_start"])
    df_obs = df_obs.sort_values("slot_start")

    baseline = df_f[df_f["forecast_version"] == "baseline_7_day_avg"].copy()
    aurora = df_f[df_f["forecast_version"] == "aurora"].copy()
    for df in (baseline, aurora):
        if not df.empty:
            df["slot_start"] = pd.to_datetime(df["slot_start"])

    merged = df_obs.copy()
    if not baseline.empty:
        merged = merged.merge(
            baseline[["slot_start", "pv_forecast_kwh", "load_forecast_kwh"]],
            on="slot_start",
            how="left",
            suffixes=("", "_baseline"),
        )
    if not aurora.empty:
        merged = merged.merge(
            aurora[
                [
                    "slot_start",
                    "pv_forecast_kwh",
                    "load_forecast_kwh",
                    "pv_p10",
                    "pv_p90",
                    "load_p10",
                    "load_p90",
                ]
            ],
            on="slot_start",
            how="left",
            suffixes=("", "_aurora"),
        )

    slots = []
    for _, row in merged.iterrows():
        slots.append(
            {
                "slot_start": pd.to_datetime(row["slot_start"]).isoformat(),
                "pv_kwh": None if pd.isna(row.get("pv_kwh")) else float(row["pv_kwh"]),
                "load_kwh": None if pd.isna(row.get("load_kwh")) else float(row["load_kwh"]),
                "baseline_pv": (
                    None
                    if pd.isna(row.get("pv_forecast_kwh_baseline"))
                    else float(row["pv_forecast_kwh_baseline"])
                ),
                "baseline_load": (
                    None
                    if pd.isna(row.get("load_forecast_kwh_baseline"))
                    else float(row["load_forecast_kwh_baseline"])
                ),
                "aurora_pv": (
                    None
                    if pd.isna(row.get("pv_forecast_kwh_aurora"))
                    else float(row["pv_forecast_kwh_aurora"])
                ),
                "aurora_load": (
                    None
                    if pd.isna(row.get("load_forecast_kwh_aurora"))
                    else float(row["load_forecast_kwh_aurora"])
                ),
                "aurora_pv_p10": (
                    None if pd.isna(row.get("pv_p10_aurora")) else float(row["pv_p10_aurora"])
                ),
                "aurora_pv_p90": (
                    None if pd.isna(row.get("pv_p90_aurora")) else float(row["pv_p90_aurora"])
                ),
                "aurora_load_p10": (
                    None if pd.isna(row.get("load_p10_aurora")) else float(row["load_p10_aurora"])
                ),
                "aurora_load_p90": (
                    None if pd.isna(row.get("load_p90_aurora")) else float(row["load_p90_aurora"])
                ),
            }
        )

    return jsonify({"date": target_date.isoformat(), "slots": slots})


@app.route("/api/theme", methods=["POST"])
def select_theme():
    """Persist a selected theme to config.yaml."""
    global AVAILABLE_THEMES
    AVAILABLE_THEMES = load_themes()

    payload = request.get_json(silent=True) or {}
    theme_name = payload.get("theme")
    if theme_name not in AVAILABLE_THEMES:
        return jsonify({"error": f"Theme '{theme_name}' not found"}), 404
    accent_index = payload.get("accent_index")
    try:
        accent_index = int(accent_index) if accent_index is not None else None
    except (TypeError, ValueError):
        accent_index = None
    if accent_index is not None and not 0 <= accent_index <= 15:
        return jsonify({"error": "accent_index must be between 0 and 15"}), 400

    try:
        with open("config.yaml", "r") as handle:
            config = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        config = {}

    ui_section = config.setdefault("ui", {})
    ui_section["theme"] = theme_name
    if accent_index is not None:
        ui_section["theme_accent_index"] = accent_index

    with open("config.yaml", "w") as handle:
        yaml.safe_dump(config, handle, default_flow_style=False)

    return jsonify(
        {
            "status": "success",
            "current": theme_name,
            "accent_index": accent_index,
            "theme": AVAILABLE_THEMES[theme_name],
        }
    )


@app.route("/api/schedule")
def get_schedule():
    with open("schedule.json", "r") as f:
        data = json.load(f)

    # Add price overlay for historical slots if missing
    if "schedule" in data:
        # Build price map using same logic as /api/db/current_schedule
        price_map = {}
        try:
            from inputs import get_nordpool_data

            price_slots = get_nordpool_data("config.yaml")
            tz = pytz.timezone("Europe/Stockholm")
            for p in price_slots:
                st = p["start_time"]
                if st.tzinfo is None:
                    st_local_naive = tz.localize(st).replace(tzinfo=None)
                else:
                    st_local_naive = st.astimezone(tz).replace(tzinfo=None)
                price_map[st_local_naive] = float(p.get("import_price_sek_kwh") or 0.0)
        except Exception as exc:
            logger.warning("Price overlay unavailable in /api/schedule: %s", exc)

        # Overlay prices for slots that don't have them
        for slot in data["schedule"]:
            if "import_price_sek_kwh" not in slot:
                try:
                    start_str = slot.get("start_time")
                    if start_str:
                        start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                        local_naive = (
                            start
                            if start.tzinfo is None
                            else start.astimezone(tz).replace(tzinfo=None)
                        )
                        price = price_map.get(local_naive)
                        if price is not None:
                            slot["import_price_sek_kwh"] = round(price, 4)
                except Exception:
                    pass

    return jsonify(data)


@app.route("/api/schedule/today_with_history", methods=["GET"])
def schedule_today_with_history():
    """
    Return a merged view of today's schedule and execution history.

    For each slot_start on the local "today" date, combine:
      * planned values from schedule.json
      * executed values from MariaDB execution_history (latest executed_at per slot)
    """
    try:
        config = _load_yaml("config.yaml")
        tz_name = config.get("timezone", "Europe/Stockholm")
        tz = pytz.timezone(tz_name)
    except Exception:
        tz = pytz.timezone("Europe/Stockholm")
        tz_name = "Europe/Stockholm"

    today_local = datetime.now(tz).date()

    # Load schedule.json and filter to today's slots
    schedule_map: dict[datetime, dict] = {}
    try:
        with open("schedule.json", "r") as f:
            payload = json.load(f)
        schedule_slots = payload.get("schedule", []) or []
    except Exception:
        schedule_slots = []

    for slot in schedule_slots:
        start_str = slot.get("start_time")
        if not start_str:
            continue
        try:
            start = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
        except Exception:
            continue
        if start.tzinfo is None:
            local = tz.localize(start)
        else:
            local = start.astimezone(tz)
        if local.date() != today_local:
            continue
        key = local.replace(tzinfo=None)
        schedule_map[key] = slot

    # Load execution history for today (latest executed_at per slot_start)
    exec_map: dict[datetime, dict] = {}
    try:
        secrets = _load_yaml("secrets.yaml")
        if secrets.get("mariadb"):
            with _db_connect_from_secrets() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT e.*
                        FROM execution_history e
                        JOIN (
                            SELECT slot_start, MAX(executed_at) AS max_executed_at
                            FROM execution_history
                            WHERE DATE(slot_start) = %s
                            GROUP BY slot_start
                        ) latest
                        ON e.slot_start = latest.slot_start AND e.executed_at = latest.max_executed_at
                        ORDER BY e.slot_start ASC
                        """,
                        (today_local.isoformat(),),
                    )
                    rows = cur.fetchall() or []
            for row in rows:
                # slot_start is stored as naive local DATETIME
                slot_start = row.get("slot_start")
                if isinstance(slot_start, datetime):
                    exec_map[slot_start] = row
    except Exception as exc:
        logger.warning("Failed to read execution_history: %s", exc)

    # Build price map for today using Nordpool data (full day coverage)
    price_map: dict[datetime, float] = {}
    try:
        from inputs import get_nordpool_data

        price_slots = get_nordpool_data("config.yaml")
        for p in price_slots:
            st = p["start_time"]
            if isinstance(st, datetime):
                if st.tzinfo is None:
                    st_local = tz.localize(st)
                else:
                    st_local = st.astimezone(tz)
                if st_local.date() != today_local:
                    continue
                key = st_local.replace(tzinfo=None)
                price_map[key] = float(p.get("import_price_sek_kwh") or 0.0)
    except Exception as exc:
        logger.warning("Failed to overlay prices in /api/schedule/today_with_history: %s", exc)

    # Merge keys from schedule, execution history, and price slots
    all_keys = sorted(set(schedule_map.keys()) | set(exec_map.keys()) | set(price_map.keys()))
    merged_slots: list[dict] = []

    # Default resolution (minutes) if we need to synthesise end_time
    resolution_minutes = 15
    try:
        cfg = _load_yaml("config.yaml")
        resolution_minutes = int(
            cfg.get("nordpool", {}).get("resolution_minutes", resolution_minutes)
        )
    except Exception:
        pass

    for local_start in all_keys:
        sched = schedule_map.get(local_start)
        hist = exec_map.get(local_start)

        if sched:
            # Start from planned slot data
            slot = dict(sched)
        else:
            # Synthesise a minimal planned slot so the frontend can render history-only periods
            start_iso = tz.localize(local_start).isoformat()
            end_iso = (local_start + timedelta(minutes=resolution_minutes)).isoformat()
            slot = {
                "start_time": start_iso,
                "end_time": end_iso,
            }

        # Normalise start_time to local ISO for consistency
        local_zoned = tz.localize(local_start)
        slot["start_time"] = local_zoned.isoformat()
        if "end_time" not in slot:
            slot["end_time"] = (local_zoned + timedelta(minutes=resolution_minutes)).isoformat()

        # Attach executed values if present
        if hist:
            slot["is_executed"] = True
            # Actual SoC
            if hist.get("actual_soc") is not None:
                slot["soc_actual_percent"] = float(hist.get("actual_soc") or 0.0)
            # Actual power / energy series
            if hist.get("actual_charge_kw") is not None:
                slot["actual_charge_kw"] = float(hist.get("actual_charge_kw") or 0.0)
            if hist.get("actual_export_kw") is not None:
                slot["actual_export_kw"] = float(hist.get("actual_export_kw") or 0.0)
            if hist.get("actual_load_kwh") is not None:
                slot["actual_load_kwh"] = float(hist.get("actual_load_kwh") or 0.0)
            if hist.get("actual_pv_kwh") is not None:
                slot["actual_pv_kwh"] = float(hist.get("actual_pv_kwh") or 0.0)
        else:
            slot["is_executed"] = False

        # Attach import price if available for this slot
        price = price_map.get(local_start)
        if price is not None:
            slot["import_price_sek_kwh"] = round(price, 4)

        merged_slots.append(slot)

    return jsonify({"slots": merged_slots, "timezone": tz_name})


def _db_connect_from_secrets():
    secrets = _load_yaml("secrets.yaml")
    db = secrets.get("mariadb", {})
    if not db:
        raise RuntimeError("MariaDB credentials not found in secrets.yaml")
    return pymysql.connect(
        host=db.get("host", "127.0.0.1"),
        port=int(db.get("port", 3306)),
        user=db.get("user"),
        password=db.get("password"),
        database=db.get("database"),
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


@app.route("/api/status", methods=["GET"])
def planner_status():
    """Return last plan info from local schedule.json and MariaDB plan_history if available."""
    status = {
        "local": None,
        "db": None,
        "current_soc": None,
    }
    # Local schedule.json
    try:
        with open("schedule.json", "r") as f:
            payload = json.load(f)
        meta = payload.get("meta", {})
        status["local"] = {
            "planned_at": meta.get("planned_at"),
            "planner_version": meta.get("planner_version"),
            "s_index": meta.get("s_index"),
        }
    except Exception:
        pass

    # Current SoC from Home Assistant
    try:
        from inputs import get_initial_state

        initial_state = get_initial_state()
        if initial_state and "battery_soc_percent" in initial_state:
            status["current_soc"] = {
                "value": initial_state["battery_soc_percent"],
                "timestamp": datetime.now().isoformat(),
                "source": "home_assistant",
            }
    except Exception:
        pass

    # Database last plan
    try:
        with _db_connect_from_secrets() as conn:
            with conn.cursor() as cur:
                history_query = (
                    "SELECT planned_at, planner_version "
                    "FROM plan_history "
                    "ORDER BY planned_at DESC LIMIT 1"
                )
                cur.execute(history_query)
                row = cur.fetchone()
                if row:
                    status["db"] = {
                        "planned_at": (
                            row.get("planned_at").isoformat() if row.get("planned_at") else None
                        ),
                        "planner_version": row.get("planner_version"),
                    }
    except Exception as exc:
        status["db"] = {"error": str(exc)}

    return jsonify(status)


@app.route("/api/version", methods=["GET"])
def api_version():
    return jsonify({"version": _get_git_version()})


@app.route("/api/scheduler/status", methods=["GET"])
def scheduler_status():
    """Return the in-app scheduler status if available."""
    status_path = os.path.join("data", "scheduler_status.json")
    try:
        with open(status_path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except FileNotFoundError:
        data = {}
    except Exception as exc:
        logger.warning("Failed to read scheduler status: %s", exc)
        data = {"last_run_status": "error", "last_error": str(exc)}

    # Enrich with current automation config so UI always has a source of truth.
    try:
        cfg = _load_yaml("config.yaml")
        automation = cfg.get("automation", {}) or {}
        schedule = automation.get("schedule", {}) or {}
        if "enabled" not in data:
            data["enabled"] = bool(automation.get("enable_scheduler", False))
        if "every_minutes" not in data and "every_minutes" in schedule:
            try:
                data["every_minutes"] = int(schedule.get("every_minutes"))
            except (TypeError, ValueError):
                pass
        if "jitter_minutes" not in data and "jitter_minutes" in schedule:
            try:
                data["jitter_minutes"] = int(schedule.get("jitter_minutes"))
            except (TypeError, ValueError):
                pass
    except Exception as exc:
        logger.warning("Failed to enrich scheduler status from config.yaml: %s", exc)

    return jsonify(data)


# --- Executor API Endpoints ---
# Global executor instance (lazy-initialized)
_executor_engine = None
_executor_lock = threading.Lock()


def _get_executor():
    """Get or create the global executor engine instance."""
    global _executor_engine
    if _executor_engine is None:
        with _executor_lock:
            if _executor_engine is None:
                try:
                    from executor import ExecutorEngine

                    _executor_engine = ExecutorEngine()
                except ImportError as e:
                    logger.error("Failed to import executor: %s", e)
                    return None
    return _executor_engine


@app.route("/api/executor/status", methods=["GET"])
def executor_status():
    """Return current executor status."""
    executor = _get_executor()
    if executor is None:
        return jsonify({"error": "Executor not available"}), 500
    return jsonify(executor.get_status())


@app.route("/api/executor/toggle", methods=["POST"])
def executor_toggle():
    """Enable or disable the executor."""
    payload = request.get_json(silent=True) or {}
    enabled = payload.get("enabled")
    shadow_mode = payload.get("shadow_mode")

    if enabled is None and shadow_mode is None:
        return jsonify({"error": "Must specify 'enabled' or 'shadow_mode'"}), 400

    # Update config.yaml
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except FileNotFoundError:
        config = {}

    executor_cfg = config.setdefault("executor", {})

    if enabled is not None:
        executor_cfg["enabled"] = bool(enabled)
    if shadow_mode is not None:
        executor_cfg["shadow_mode"] = bool(shadow_mode)

    with open("config.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False)

    # Reload executor config
    executor = _get_executor()
    if executor:
        executor.reload_config()
        if enabled and executor.config.enabled:
            executor.start()
        elif enabled is False:
            executor.stop()

    return jsonify(
        {
            "success": True,
            "enabled": executor_cfg.get("enabled", False),
            "shadow_mode": executor_cfg.get("shadow_mode", False),
        }
    )


@app.route("/api/executor/run", methods=["POST"])
def executor_run():
    """Trigger a single manual execution tick."""
    executor = _get_executor()
    if executor is None:
        return jsonify({"error": "Executor not available"}), 500

    try:
        result = executor.run_once()
        return jsonify(result)
    except Exception as e:
        logger.exception("Manual executor run failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/executor/quick-action", methods=["GET", "POST", "DELETE"])
def executor_quick_action():
    """Manage quick action overrides (Force Charge/Export/Stop)."""
    executor = _get_executor()
    if executor is None:
        return jsonify({"error": "Executor not available"}), 500

    if request.method == "GET":
        # Return current quick action status
        action = executor.get_active_quick_action()
        return jsonify({"quick_action": action})

    elif request.method == "POST":
        # Set a new quick action
        payload = request.get_json(silent=True) or {}
        action_type = payload.get("type")
        duration = payload.get("duration_minutes", 30)

        if not action_type:
            return jsonify({"error": "Missing 'type' parameter"}), 400

        try:
            result = executor.set_quick_action(action_type, duration)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            logger.exception("Failed to set quick action: %s", e)
            return jsonify({"error": str(e)}), 500

    elif request.method == "DELETE":
        # Clear quick action
        result = executor.clear_quick_action()
        return jsonify(result)


@app.route("/api/executor/history", methods=["GET"])
def executor_history():
    """Return execution history with optional filters."""
    executor = _get_executor()
    if executor is None:
        return jsonify({"error": "Executor not available"}), 500

    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)
    slot_start = request.args.get("slot_start")
    success_only = request.args.get("success_only")

    if success_only is not None:
        success_only = success_only.lower() in ("true", "1", "yes")

    records = executor.history.get_history(
        limit=limit,
        offset=offset,
        slot_start=slot_start,
        success_only=success_only,
    )
    return jsonify({"records": records, "count": len(records)})


@app.route("/api/executor/stats", methods=["GET"])
def executor_stats():
    """Return execution statistics."""
    executor = _get_executor()
    if executor is None:
        return jsonify({"error": "Executor not available"}), 500

    days = request.args.get("days", 7, type=int)
    stats = executor.history.get_stats(days=days)
    return jsonify(stats)


@app.route("/api/executor/config", methods=["GET"])
def executor_config_get():
    """Return current executor configuration."""
    executor = _get_executor()
    if executor is None:
        return jsonify({"error": "Executor not available"}), 500

    cfg = executor.config
    return jsonify(
        {
            "enabled": cfg.enabled,
            "shadow_mode": cfg.shadow_mode,
            "interval_seconds": cfg.interval_seconds,
            "automation_toggle_entity": cfg.automation_toggle_entity,
            "manual_override_entity": cfg.manual_override_entity,
            "soc_target_entity": cfg.soc_target_entity,
            "inverter": {
                "work_mode_entity": cfg.inverter.work_mode_entity,
                "work_mode_export": cfg.inverter.work_mode_export,
                "work_mode_zero_export": cfg.inverter.work_mode_zero_export,
                "grid_charging_entity": cfg.inverter.grid_charging_entity,
                "max_charging_current_entity": cfg.inverter.max_charging_current_entity,
                "max_discharging_current_entity": cfg.inverter.max_discharging_current_entity,
            },
            "water_heater": {
                "target_entity": cfg.water_heater.target_entity,
                "temp_normal": cfg.water_heater.temp_normal,
                "temp_off": cfg.water_heater.temp_off,
                "temp_boost": cfg.water_heater.temp_boost,
                "temp_max": cfg.water_heater.temp_max,
            },
            "notifications": {
                "service": cfg.notifications.service,
                "on_charge_start": cfg.notifications.on_charge_start,
                "on_charge_stop": cfg.notifications.on_charge_stop,
                "on_export_start": cfg.notifications.on_export_start,
                "on_export_stop": cfg.notifications.on_export_stop,
                "on_water_heat_start": cfg.notifications.on_water_heat_start,
                "on_water_heat_stop": cfg.notifications.on_water_heat_stop,
                "on_soc_target_change": cfg.notifications.on_soc_target_change,
                "on_override_activated": cfg.notifications.on_override_activated,
                "on_error": cfg.notifications.on_error,
            },
        }
    )


@app.route("/api/executor/config", methods=["PUT"])
def executor_config_put():
    """Update executor entity configuration."""
    from ruamel.yaml import YAML

    payload = request.get_json(silent=True) or {}

    try:
        yaml_handler = YAML()
        yaml_handler.preserve_quotes = True

        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml_handler.load(f)

        if "executor" not in config:
            config["executor"] = {}

        executor_cfg = config["executor"]

        # Update soc_target_entity
        if "soc_target_entity" in payload:
            executor_cfg["soc_target_entity"] = payload["soc_target_entity"]

        # Update inverter entities
        if "inverter" in payload:
            if "inverter" not in executor_cfg:
                executor_cfg["inverter"] = {}
            inv = executor_cfg["inverter"]
            inv_payload = payload["inverter"]
            if "work_mode_entity" in inv_payload:
                inv["work_mode_entity"] = inv_payload["work_mode_entity"]
            if "grid_charging_entity" in inv_payload:
                inv["grid_charging_entity"] = inv_payload["grid_charging_entity"]
            if "max_charging_current_entity" in inv_payload:
                inv["max_charging_current_entity"] = inv_payload["max_charging_current_entity"]
            if "max_discharging_current_entity" in inv_payload:
                inv["max_discharging_current_entity"] = inv_payload[
                    "max_discharging_current_entity"
                ]

        # Update water heater entities
        if "water_heater" in payload:
            if "water_heater" not in executor_cfg:
                executor_cfg["water_heater"] = {}
            wh = executor_cfg["water_heater"]
            wh_payload = payload["water_heater"]
            if "target_entity" in wh_payload:
                wh["target_entity"] = wh_payload["target_entity"]
            if "temp_normal" in wh_payload:
                wh["temp_normal"] = wh_payload["temp_normal"]
            if "temp_off" in wh_payload:
                wh["temp_off"] = wh_payload["temp_off"]
            if "temp_boost" in wh_payload:
                wh["temp_boost"] = wh_payload["temp_boost"]
            if "temp_max" in wh_payload:
                wh["temp_max"] = wh_payload["temp_max"]

        with open("config.yaml", "w", encoding="utf-8") as f:
            yaml_handler.dump(config, f)

        # Reload executor config
        executor = _get_executor()
        if executor:
            executor.reload_config()

        return jsonify({"success": True})
    except Exception as e:
        logger.exception("Failed to update executor config: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/executor/notifications", methods=["GET", "POST"])
def executor_notifications():
    """Get or update executor notification settings."""
    if request.method == "GET":
        # Return current notification settings
        executor = _get_executor()
        if executor is None:
            return jsonify({"error": "Executor not available"}), 500

        cfg = executor.config.notifications
        return jsonify(
            {
                "service": cfg.service,
                "on_charge_start": cfg.on_charge_start,
                "on_charge_stop": cfg.on_charge_stop,
                "on_export_start": cfg.on_export_start,
                "on_export_stop": cfg.on_export_stop,
                "on_water_heat_start": cfg.on_water_heat_start,
                "on_water_heat_stop": cfg.on_water_heat_stop,
                "on_soc_target_change": cfg.on_soc_target_change,
                "on_override_activated": cfg.on_override_activated,
                "on_error": cfg.on_error,
            }
        )

    # POST - Update notification settings
    payload = request.get_json(silent=True) or {}

    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except FileNotFoundError:
        config = {}

    notifications = config.setdefault("executor", {}).setdefault("notifications", {})

    # Update only provided fields
    valid_keys = [
        "service",
        "on_charge_start",
        "on_charge_stop",
        "on_export_start",
        "on_export_stop",
        "on_water_heat_start",
        "on_water_heat_stop",
        "on_soc_target_change",
        "on_override_activated",
        "on_error",
    ]

    for key in valid_keys:
        if key in payload:
            notifications[key] = payload[key]

    with open("config.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False)

    # Reload executor config
    executor = _get_executor()
    if executor:
        executor.reload_config()

    return jsonify({"success": True, "notifications": notifications})


@app.route("/api/executor/notifications/test", methods=["POST"])
def executor_notifications_test():
    """Send a test notification via Home Assistant."""
    print("[BACKEND] Test notification endpoint called")

    try:
        print("[BACKEND] Step 1: Importing modules")
        from inputs import load_home_assistant_config, _make_ha_headers
        import requests as req

        print("[BACKEND] Step 2: Loading HA config")
        ha_config = load_home_assistant_config()
        if not ha_config:
            print("[BACKEND] ERROR: HA not configured")
            return jsonify({"error": "HA not configured"}), 500

        base_url = ha_config.get("url", "").rstrip("/")
        token = ha_config.get("token", "")
        print(f"[BACKEND] Step 3: base_url={base_url}, token={'*'*10 if token else 'MISSING'}")

        if not base_url or not token:
            return jsonify({"error": "Missing HA URL or token"}), 500

        headers = _make_ha_headers(token)
        print(f"[BACKEND] Step 4: Headers created")

        # Get notification service from config
        print("[BACKEND] Step 5: Loading config.yaml")
        config = _load_yaml("config.yaml")
        service = config.get("executor", {}).get("notifications", {}).get("service", "")
        print(f"[BACKEND] Step 6: Service from config = '{service}'")

        if not service:
            return jsonify({"error": "No notification service configured"}), 400

        # n8n uses domain "notify" and service "mobile_app_X"
        # Config has "notify.mobile_app_phone" - need to split
        if "." in service:
            service_domain, service_name = service.split(".", 1)
        else:
            service_domain = "notify"
            service_name = service

        print(f"[BACKEND] Step 7: domain={service_domain}, service={service_name}")

        # n8n format: just "message" attribute, no "title"
        payload = {"message": "⚡ Darkstar test notification! Executor is working correctly."}

        url = f"{base_url}/api/services/{service_domain}/{service_name}"
        print(f"[BACKEND] Step 8: Calling {url}")
        print(f"[BACKEND] Step 9: Payload = {payload}")

        response = req.post(url, headers=headers, json=payload, timeout=10)

        print(f"[BACKEND] Step 10: Response status={response.status_code}")
        print(
            f"[BACKEND] Step 11: Response body={response.text[:500] if response.text else 'empty'}"
        )

        if response.ok:
            return jsonify({"success": True, "message": f"Test notification sent via {service}"})
        else:
            return jsonify({"error": f"HA error ({response.status_code}): {response.text}"}), 500

    except Exception as e:
        import traceback

        print(f"[BACKEND] EXCEPTION: {e}")
        print(f"[BACKEND] TRACEBACK:\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/executor/live", methods=["GET"])
def executor_live():
    """Return current live values from Home Assistant for the executor dashboard."""
    try:
        from inputs import load_home_assistant_config, _make_ha_headers
        import requests as req

        ha_config = load_home_assistant_config()
        if not ha_config:
            return jsonify({"error": "HA not configured"}), 500

        base_url = ha_config.get("url", "").rstrip("/")
        token = ha_config.get("token", "")

        if not base_url or not token:
            return jsonify({"error": "Missing HA URL or token"}), 500

        headers = _make_ha_headers(token)

        # Load config to get entity IDs
        config = _load_yaml("config.yaml")
        input_sensors = config.get("input_sensors", {})
        executor_cfg = config.get("executor", {})
        inverter_cfg = executor_cfg.get("inverter", {})

        entities = {
            "soc": input_sensors.get("battery_soc", "sensor.inverter_battery"),
            "pv_power": input_sensors.get("pv_power", "sensor.inverter_pv_power"),
            "load_power": input_sensors.get("load_power", "sensor.inverter_load_power"),
            "grid_import": input_sensors.get(
                "grid_import_power", "sensor.inverter_grid_import_power"
            ),
            "grid_export": input_sensors.get(
                "grid_export_power", "sensor.inverter_grid_export_power"
            ),
            "work_mode": inverter_cfg.get("work_mode_entity", "select.inverter_work_mode"),
            "grid_charging": inverter_cfg.get(
                "grid_charging_entity", "switch.inverter_battery_grid_charging"
            ),
        }

        result = {}
        for key, entity_id in entities.items():
            try:
                r = req.get(f"{base_url}/api/states/{entity_id}", headers=headers, timeout=5)
                if r.ok:
                    data = r.json()
                    state = data.get("state")
                    if state not in ("unknown", "unavailable"):
                        result[key] = {
                            "value": state,
                            "unit": data.get("attributes", {}).get("unit_of_measurement", ""),
                            "friendly_name": data.get("attributes", {}).get(
                                "friendly_name", entity_id
                            ),
                        }
                        # Try to convert to float for numeric values
                        try:
                            result[key]["numeric"] = float(state)
                        except (ValueError, TypeError):
                            pass
            except Exception as e:
                print(f"[BACKEND] Failed to get {entity_id}: {e}")

        return jsonify(result)
    except Exception as e:
        print(f"[BACKEND] Executor live error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/db/current_schedule", methods=["GET"])
def db_current_schedule():
    """Return the current_schedule from MariaDB in the same shape used by the UI."""
    try:
        config = _load_yaml("config.yaml")
        resolution_minutes = int(config.get("nordpool", {}).get("resolution_minutes", 15))
        tz_name = config.get("timezone", "Europe/Stockholm")
        tz = pytz.timezone(tz_name)

        with _db_connect_from_secrets() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT slot_number, slot_start, charge_kw, export_kw, water_kw,
                           planned_load_kwh, planned_pv_kwh,
                           soc_target, soc_projected, planner_version
                    FROM current_schedule
                    ORDER BY slot_number ASC
                    """
                )
                rows = cur.fetchall() or []

        # Load execution history for today (latest executed_at per slot_start)
        exec_map: dict[datetime, dict] = {}
        today_local = datetime.now(tz).date()
        try:
            secrets = _load_yaml("secrets.yaml")
            if secrets.get("mariadb"):
                with _db_connect_from_secrets() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT e.*
                            FROM execution_history e
                            JOIN (
                                SELECT slot_start, MAX(executed_at) AS max_executed_at
                                FROM execution_history
                                WHERE DATE(slot_start) = %s
                                GROUP BY slot_start
                            ) latest
                            ON e.slot_start = latest.slot_start AND e.executed_at = latest.max_executed_at
                            ORDER BY e.slot_start ASC
                            """,
                            (today_local.isoformat(),),
                        )
                        hist_rows = cur.fetchall() or []
                for row in hist_rows:
                    slot_start = row.get("slot_start")
                    if isinstance(slot_start, datetime):
                        exec_map[slot_start] = row
        except Exception as exc:
            logger.warning("Failed to read execution_history in /api/db/current_schedule: %s", exc)

        # Build a price map keyed by local naive start time so DB rows get price overlays
        price_map = {}
        try:
            from inputs import get_nordpool_data

            price_slots = get_nordpool_data("config.yaml")
            for p in price_slots:
                st = p["start_time"]
                if st.tzinfo is None:
                    st_local_naive = tz.localize(st).replace(tzinfo=None)
                else:
                    st_local_naive = st.astimezone(tz).replace(tzinfo=None)
                price_map[st_local_naive] = float(p.get("import_price_sek_kwh") or 0.0)
        except Exception as exc:
            logger.warning("Price overlay unavailable in /api/db/current_schedule: %s", exc)

        schedule = []
        seen_starts: set[datetime] = set()
        for r in rows:
            start = r["slot_start"]
            # slot_start is DATETIME; compute end_time from resolution
            try:
                end = start + pd.Timedelta(minutes=resolution_minutes)
                stored_charge = float(r.get("charge_kw") or 0.0)
                record = {
                    "slot_number": r.get("slot_number"),
                    "start_time": start.isoformat(),
                    "end_time": end.isoformat(),
                    "battery_charge_kw": round(max(stored_charge, 0.0), 2),
                    "battery_discharge_kw": round(max(-stored_charge, 0.0), 2),
                    # DB stores export in kW; UI expects export_kwh (15-min → kWh = kW/4)
                    "export_kwh": round(float(r.get("export_kw") or 0.0) / 4.0, 4),
                    "water_heating_kw": round(float(r.get("water_kw") or 0.0), 2),
                    "load_forecast_kwh": round(float(r.get("planned_load_kwh") or 0.0), 4),
                    "pv_forecast_kwh": round(float(r.get("planned_pv_kwh") or 0.0), 4),
                    "soc_target_percent": round(float(r.get("soc_target") or 0.0), 2),
                    "projected_soc_percent": round(float(r.get("soc_projected") or 0.0), 2),
                }
            except Exception:
                # Fallback if not datetime (string), try parse
                start_dt = datetime.fromisoformat(str(start))
                end = start_dt + pd.Timedelta(minutes=resolution_minutes)
                start = start_dt

                stored_charge = float(r.get("charge_kw") or 0.0)
                record = {
                    "slot_number": r.get("slot_number"),
                    "start_time": start.isoformat(),
                    "end_time": end.isoformat(),
                    "battery_charge_kw": round(max(stored_charge, 0.0), 2),
                    "battery_discharge_kw": round(max(-stored_charge, 0.0), 2),
                    "export_kwh": round(float(r.get("export_kw") or 0.0) / 4.0, 4),
                    "water_heating_kw": round(float(r.get("water_kw") or 0.0), 2),
                    "load_forecast_kwh": round(float(r.get("planned_load_kwh") or 0.0), 4),
                    "pv_forecast_kwh": round(float(r.get("planned_pv_kwh") or 0.0), 4),
                    "soc_target_percent": round(float(r.get("soc_target") or 0.0), 2),
                    "projected_soc_percent": round(float(r.get("soc_projected") or 0.0), 2),
                }

            # Attach executed values if present for today's slots
            try:
                if isinstance(start, datetime) and start.date() == today_local:
                    hist = exec_map.get(start)
                    if hist:
                        record["is_executed"] = True
                        if hist.get("actual_soc") is not None:
                            record["soc_actual_percent"] = float(hist.get("actual_soc") or 0.0)
                        if hist.get("actual_charge_kw") is not None:
                            record["actual_charge_kw"] = float(hist.get("actual_charge_kw") or 0.0)
                        if hist.get("actual_export_kw") is not None:
                            record["actual_export_kw"] = float(hist.get("actual_export_kw") or 0.0)
                        if hist.get("actual_load_kwh") is not None:
                            record["actual_load_kwh"] = float(hist.get("actual_load_kwh") or 0.0)
                        if hist.get("actual_pv_kwh") is not None:
                            record["actual_pv_kwh"] = float(hist.get("actual_pv_kwh") or 0.0)
                    else:
                        record["is_executed"] = False
                else:
                    record["is_executed"] = False
            except Exception:
                # If anything goes wrong with history lookup, fall back to plan-only view.
                record.setdefault("is_executed", False)
            # Overlay import price if available
            try:
                local_naive = (
                    start if start.tzinfo is None else start.astimezone(tz).replace(tzinfo=None)
                )
                price = price_map.get(local_naive)
                if price is not None:
                    record["import_price_sek_kwh"] = round(price, 4)
            except Exception:
                pass
            schedule.append(record)
            if isinstance(start, datetime):
                seen_starts.add(start.replace(tzinfo=None))

        # Pad in any history-only slots for today that don't exist in current_schedule
        try:
            for hist_start, hist in exec_map.items():
                # hist_start is naive local datetime
                if hist_start.date() != today_local:
                    continue
                if hist_start in seen_starts:
                    continue
                local_zoned = tz.localize(hist_start)
                end = local_zoned + timedelta(minutes=resolution_minutes)
                record = {
                    "start_time": local_zoned.isoformat(),
                    "end_time": end.isoformat(),
                    "is_executed": True,
                }
                if hist.get("actual_soc") is not None:
                    record["soc_actual_percent"] = float(hist.get("actual_soc") or 0.0)
                if hist.get("actual_charge_kw") is not None:
                    record["actual_charge_kw"] = float(hist.get("actual_charge_kw") or 0.0)
                if hist.get("actual_export_kw") is not None:
                    record["actual_export_kw"] = float(hist.get("actual_export_kw") or 0.0)
                if hist.get("actual_load_kwh") is not None:
                    record["actual_load_kwh"] = float(hist.get("actual_load_kwh") or 0.0)
                if hist.get("actual_pv_kwh") is not None:
                    record["actual_pv_kwh"] = float(hist.get("actual_pv_kwh") or 0.0)
                # Overlay price for this history-only slot if available
                local_naive = hist_start
                price = price_map.get(local_naive)
                if price is not None:
                    record["import_price_sek_kwh"] = round(price, 4)
                schedule.append(record)
        except Exception as exc:
            logger.warning("Failed to pad history-only slots in /api/db/current_schedule: %s", exc)

        meta = {
            "source": "mariadb",
            "planner_version": rows[0]["planner_version"] if rows else None,
        }
        return jsonify({"schedule": schedule, "meta": meta})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/db/push_current", methods=["POST"])
def db_push_current():
    """Write the current local schedule.json to MariaDB regardless of automation toggles."""
    try:
        config = _load_yaml("config.yaml")
        secrets = _load_yaml("secrets.yaml")
        # Determine a sensible planner_version fallback for when meta is missing
        fallback_version = config.get("version")
        if not fallback_version:
            try:
                # Prefer tags, else short SHA; mark dirty if needed
                fallback_version = (
                    subprocess.check_output(
                        ["git", "describe", "--tags", "--always", "--dirty"],
                        stderr=subprocess.DEVNULL,
                    )
                    .decode()
                    .strip()
                )
            except Exception:
                fallback_version = "dev"

        inserted = write_schedule_to_db("schedule.json", fallback_version, config, secrets)
        return jsonify({"status": "success", "rows": inserted})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/schedule/save", methods=["POST"])
def save_schedule_json():
    """Persist a provided schedule payload to schedule.json while keeping historical slots."""
    try:
        payload = request.get_json(silent=True) or {}
        manual_schedule = payload.get("schedule") if isinstance(payload, dict) else None
        if manual_schedule is None and isinstance(payload, list):
            manual_schedule = payload
        if not isinstance(manual_schedule, list):
            return jsonify({"status": "error", "error": "Invalid schedule payload"}), 400

        # Preserve historical slots from database (same logic as planner.py) and
        # only merge FUTURE records from the provided payload to avoid duplicates.
        try:
            from db_writer import get_preserved_slots
            import pytz

            tz = pytz.timezone("Europe/Stockholm")
            now = datetime.now(tz)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

            # Load secrets for DB access
            secrets = _load_yaml("secrets.yaml")
            existing_past_slots = get_preserved_slots(
                today_start,
                now,
                secrets,
                tz_name=tz.zone if hasattr(tz, "zone") else "Europe/Stockholm",
            )

            # Filter incoming to future-only
            future_schedule = []
            for rec in manual_schedule:
                try:
                    start_str = rec.get("start_time") or rec.get("start")
                    if not start_str:
                        continue
                    dt = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = tz.localize(dt)
                    else:
                        dt = dt.astimezone(tz)
                    if dt >= now:
                        future_schedule.append(rec)
                except Exception:
                    # If parsing fails, keep conservative and skip the record
                    continue

            # Fix slot number conflicts: continue after historical max
            max_historical_slot = 0
            if existing_past_slots:
                max_historical_slot = max(
                    slot.get("slot_number", 0) for slot in existing_past_slots
                )
            for i, record in enumerate(future_schedule):
                record["slot_number"] = max_historical_slot + i + 1

            # Merge preserved past + future-only incoming
            merged_schedule = existing_past_slots + future_schedule

            # De-duplicate by start_time (keep first occurrence)
            seen = set()
            deduped = []
            for slot in merged_schedule:
                start_val = slot.get("start_time") or slot.get("slot_datetime")
                if not start_val:
                    deduped.append(slot)
                    continue
                key = str(start_val)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(slot)
            merged_schedule = deduped

        except Exception as e:
            logger.warning("Could not preserve historical slots for manual changes: %s", e)
            # Fallback: write the provided schedule as-is
            merged_schedule = manual_schedule

        # Build meta with version + timestamp
        version = _get_git_version()

        out = {
            "schedule": merged_schedule,
            "meta": {
                "planned_at": datetime.now().isoformat(),
                "planner_version": version,
            },
        }
        with open("schedule.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/config", methods=["GET"])
def get_config():
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
    return jsonify(config)


@app.route("/api/initial_state", methods=["GET"])
def get_initial_state():
    try:
        from inputs import get_initial_state

        initial_state = get_initial_state()
        return jsonify(initial_state)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _validate_config(cfg: dict) -> list[dict]:
    """Return a list of field error dicts: {'field': 'path', 'message': '...'}."""
    errors: list[dict] = []

    def add(field: str, message: str) -> None:
        errors.append({"field": field, "message": message})

    # Battery constraints
    battery = cfg.get("battery", {}) or {}
    cap = battery.get("capacity_kwh")
    if cap is not None:
        try:
            if float(cap) <= 0:
                add("battery.capacity_kwh", "Battery capacity must be greater than 0.")
        except (TypeError, ValueError):
            add("battery.capacity_kwh", "Battery capacity must be a number.")

    min_soc = battery.get("min_soc_percent")
    max_soc = battery.get("max_soc_percent")
    try:
        min_soc_val = float(min_soc) if min_soc is not None else None
        max_soc_val = float(max_soc) if max_soc is not None else None
    except (TypeError, ValueError):
        min_soc_val = None
        max_soc_val = None

    if min_soc_val is not None:
        if not 0 <= min_soc_val <= 100:
            add("battery.min_soc_percent", "Min SoC must be between 0 and 100.")
    if max_soc_val is not None:
        if not 0 <= max_soc_val <= 100:
            add("battery.max_soc_percent", "Max SoC must be between 0 and 100.")
    if min_soc_val is not None and max_soc_val is not None:
        if min_soc_val >= max_soc_val:
            add(
                "battery.min_soc_percent",
                "Min SoC must be strictly less than Max SoC.",
            )

    for key, field_name in [
        ("max_charge_power_kw", "battery.max_charge_power_kw"),
        ("max_discharge_power_kw", "battery.max_discharge_power_kw"),
    ]:
        v = battery.get(key)
        if v is not None:
            try:
                if float(v) < 0:
                    add(field_name, "Power limit must be zero or positive.")
            except (TypeError, ValueError):
                add(field_name, "Power limit must be a number.")

    # Nordpool resolution
    nordpool = cfg.get("nordpool", {}) or {}
    res = nordpool.get("resolution_minutes")
    if res is not None:
        try:
            res_val = int(res)
            if res_val not in (15, 30, 60):
                add(
                    "nordpool.resolution_minutes",
                    "Resolution must be one of 15, 30, or 60 minutes.",
                )
        except (TypeError, ValueError):
            add("nordpool.resolution_minutes", "Resolution must be an integer.")

    # Timezone (basic check: non-empty string)
    tz_name = cfg.get("timezone")
    if tz_name is None or not str(tz_name).strip():
        add("timezone", "Timezone is required.")

    # S-index
    s_index = cfg.get("s_index", {}) or {}
    base_factor = s_index.get("base_factor", s_index.get("static_factor"))
    max_factor = s_index.get("max_factor")
    try:
        base_val = float(base_factor) if base_factor is not None else None
        max_val = float(max_factor) if max_factor is not None else None
    except (TypeError, ValueError):
        base_val = None
        max_val = None

    if base_val is not None and base_val <= 0:
        add("s_index.base_factor", "Base factor must be greater than 0.")
    if max_val is not None and max_val <= 0:
        add("s_index.max_factor", "Max factor must be greater than 0.")
    if base_val is not None and max_val is not None and max_val < base_val:
        add("s_index.max_factor", "Max factor must be >= base factor.")

    # Learning thresholds
    learning_cfg = cfg.get("learning", {}) or {}
    if "min_sample_threshold" in learning_cfg:
        try:
            if int(learning_cfg["min_sample_threshold"]) < 0:
                add("learning.min_sample_threshold", "Value must be zero or positive.")
        except (TypeError, ValueError):
            add("learning.min_sample_threshold", "Value must be an integer.")
    if "min_improvement_threshold" in learning_cfg:
        try:
            if float(learning_cfg["min_improvement_threshold"]) < 0:
                add("learning.min_improvement_threshold", "Value must be zero or positive.")
        except (TypeError, ValueError):
            add("learning.min_improvement_threshold", "Value must be a number.")

    return errors


@app.route("/api/config/save", methods=["POST"])
def save_config():
    # Load current config first
    with open("config.yaml", "r") as f:
        current_config = yaml.safe_load(f) or {}

    # Get the new config data from the request
    new_config = request.get_json() or {}

    # Deep merge the new config into the current config
    def deep_merge(current, new):
        for key, value in new.items():
            if key in current and isinstance(current[key], dict) and isinstance(value, dict):
                deep_merge(current[key], value)
            else:
                current[key] = value
        return current

    merged_config = deep_merge(current_config, new_config)

    # Ensure critical defaults are preserved
    if "nordpool" not in merged_config:
        merged_config["nordpool"] = {}
    if "resolution_minutes" not in merged_config["nordpool"]:
        merged_config["nordpool"]["resolution_minutes"] = 15
    if "price_area" not in merged_config["nordpool"]:
        merged_config["nordpool"]["price_area"] = "SE4"
    if "currency" not in merged_config["nordpool"]:
        merged_config["nordpool"]["currency"] = "SEK"

    # Validate merged config before writing
    errors = _validate_config(merged_config)
    if errors:
        return jsonify({"status": "error", "errors": errors})

    with open("config.yaml", "w") as f:
        yaml.dump(merged_config, f, default_flow_style=False)

    # Regenerate schedule if s_index or battery settings changed
    # This ensures risk_appetite changes are immediately reflected
    regenerate_schedule = False
    if "s_index" in new_config or "battery" in new_config:
        regenerate_schedule = True

    regen_result = None
    if regenerate_schedule:
        try:
            from inputs import get_all_input_data
            from planner.pipeline import PlannerPipeline

            logger.info("Config changed - regenerating schedule...")

            # CRITICAL: Reload the fresh config from disk to ensure all values are correct
            # The merged_config from the request may be incomplete or have stale values
            with open("config.yaml", "r") as f:
                fresh_config = yaml.safe_load(f) or {}

            input_data = get_all_input_data("config.yaml")
            pipeline = PlannerPipeline(fresh_config)
            pipeline.generate_schedule(input_data, mode="full", save_to_file=True)
            logger.info("Schedule regenerated successfully")
            regen_result = "success"
        except Exception as exc:
            logger.warning("Failed to regenerate schedule after config change: %s", exc)
            regen_result = f"error: {exc}"

    return jsonify(
        {"status": "success", "regenerated": regenerate_schedule, "regen_result": regen_result}
    )


@app.route("/api/config/reset", methods=["POST"])
def reset_config():
    shutil.copy("config.default.yaml", "config.yaml")
    return jsonify({"status": "success"})


@app.route("/api/run_planner", methods=["POST"])
def run_planner():
    try:
        input_data = get_all_input_data()

        # Load config raw to init engine
        with open("config.yaml", "r") as f:
            base_config = yaml.safe_load(f) or {}

        # 1. Aurora Strategy Decision
        strategy = StrategyEngine(base_config)
        overrides = strategy.decide(input_data)

        # 2. Planner Execution (UI/Lab runs must not pollute training episodes)
        # 2. Planner Execution (UI/Lab runs must not pollute training episodes)
        pipeline = PlannerPipeline(base_config)
        df = pipeline.generate_schedule(
            input_data, overrides=overrides, record_training_episode=False
        )

        # Store per-slot PV/load forecasts in the learning database so
        # the learning engine can calibrate forecast accuracy over time.
        try:
            engine = get_learning_engine()
            if engine.learning_config.get("enable", False) and df is not None:
                forecast_rows = []
                for ts, row in df.iterrows():
                    try:
                        slot_start = ts.isoformat()
                    except Exception:
                        continue
                    forecast_rows.append(
                        {
                            "slot_start": slot_start,
                            "pv_forecast_kwh": float(row.get("pv_forecast_kwh") or 0.0),
                            "load_forecast_kwh": float(row.get("load_forecast_kwh") or 0.0),
                            # Temperature per slot is optional here; can be extended later
                            "temp_c": None,
                        }
                    )
                if forecast_rows:
                    engine.store_forecasts(forecast_rows, forecast_version=_get_git_version())
        except Exception as exc:
            logger.info("Skipping forecast storage in learning DB: %s", exc)

        # Clear any previous error from schedule.json on success
        try:
            schedule_path = "schedule.json"
            with open(schedule_path, "r", encoding="utf-8") as f:
                schedule_data = json.load(f)
            if "meta" in schedule_data:
                # Remove error fields if present
                schedule_data["meta"].pop("last_error", None)
                schedule_data["meta"].pop("last_error_at", None)
                with open(schedule_path, "w", encoding="utf-8") as f:
                    json.dump(schedule_data, f, indent=2, ensure_ascii=False)
        except Exception as clear_err:
            logger.debug("Could not clear last_error from schedule.json: %s", clear_err)

        return jsonify({"status": "success", "message": "Planner run completed successfully."})
    except Exception as e:
        error_msg = str(e)
        logger.exception("Planner run failed: %s", error_msg)

        # Persist error to schedule.json for frontend display
        try:
            error_time = datetime.now().isoformat()
            schedule_path = "schedule.json"

            # Load existing schedule if it exists
            try:
                with open(schedule_path, "r", encoding="utf-8") as f:
                    schedule_data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                schedule_data = {"schedule": [], "meta": {}}

            # Update meta with error
            if "meta" not in schedule_data:
                schedule_data["meta"] = {}
            schedule_data["meta"]["last_error"] = error_msg
            schedule_data["meta"]["last_error_at"] = error_time

            with open(schedule_path, "w", encoding="utf-8") as f:
                json.dump(schedule_data, f, indent=2, ensure_ascii=False)
        except Exception as persist_err:
            logger.warning("Failed to persist error to schedule.json: %s", persist_err)

        # Send notification via HA-first, Discord fallback
        try:
            from backend.notify import send_critical_notification
            from inputs import load_home_assistant_config

            ha_config = load_home_assistant_config() or {}

            with open("config.yaml", "r") as f:
                config = yaml.safe_load(f) or {}

            executor_cfg = config.get("executor", {})
            notif_cfg = executor_cfg.get("notifications", {})

            send_critical_notification(
                title="Darkstar Planner Failed",
                message=error_msg,
                ha_service=notif_cfg.get("service"),
                ha_url=ha_config.get("url"),
                ha_token=ha_config.get("token"),
                discord_webhook_url=notif_cfg.get("discord_webhook_url"),
            )
        except Exception as notif_err:
            logger.warning("Failed to send planner error notification: %s", notif_err)

        return jsonify({"status": "error", "message": f"An error occurred: {error_msg}"}), 500


@app.route("/api/analyst/run", methods=["GET"])
def run_analyst():
    try:
        with open("schedule.json", "r") as f:
            schedule_data = json.load(f)
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
        analyst = EnergyAnalyst(schedule_data, config)
        report = analyst.analyze()
        return jsonify(report)
    except FileNotFoundError:
        return jsonify({"error": "Data not found. Run planner first."}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/analyst/advice", methods=["GET"])
def get_analyst_advice():
    try:
        with open("schedule.json", "r") as f:
            schedule_data = json.load(f)
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)

        if not config.get("advisor", {}).get("enable_llm", False):
            return jsonify({"advice": None, "status": "disabled"})

        current_planned_at = schedule_data.get("meta", {}).get("planned_at")
        if _advice_cache["planned_at"] == current_planned_at and _advice_cache["text"]:
            return jsonify(
                {
                    "advice": _advice_cache["text"],
                    "cached": True,
                    "report": None,
                }
            )

        analyst = EnergyAnalyst(schedule_data, config)
        report = analyst.analyze()

        secrets = _load_yaml("secrets.yaml")
        text = get_advice(report, config, secrets)

        _advice_cache["planned_at"] = current_planned_at
        _advice_cache["text"] = text

        return jsonify({"advice": text, "cached": False, "report": report})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/ha/average", methods=["GET"])
def ha_average():
    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
        profile = _get_load_profile_from_ha(config)
        daily_kwh = round(sum(profile), 2)
        avg_kw = round(daily_kwh / 24.0, 2)
        return jsonify({"daily_kwh": daily_kwh, "average_load_kw": avg_kw})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/forecast/horizon", methods=["GET"])
def forecast_horizon():
    """Return information about the forecast horizon based on current schedule.json."""
    try:
        with open("schedule.json", "r") as f:
            data = json.load(f)
        schedule = data.get("schedule", [])
        tz = pytz.timezone("Europe/Stockholm")
        dates = set()
        pv_dates = set()
        load_dates = set()
        for slot in schedule:
            dt = datetime.fromisoformat(slot["start_time"])
            if dt.tzinfo is None:
                dt = tz.localize(dt)
            else:
                dt = dt.astimezone(tz)
            d = dt.date().isoformat()
            dates.add(d)
            if slot.get("pv_forecast_kwh") is not None:
                pv_dates.add(d)
            if slot.get("load_forecast_kwh") is not None:
                load_dates.add(d)

        debug = data.get("debug", {})
        s_index = debug.get("s_index", {})
        considered_days = s_index.get("considered_days")

        forecast_meta = data.get("meta", {}).get("forecast", {})

        return jsonify(
            {
                "total_days_in_schedule": len(dates),
                "days_list": sorted(list(dates)),
                "pv_days_schedule": len(pv_dates),
                "load_days_schedule": len(load_dates),
                "pv_forecast_days": forecast_meta.get("pv_forecast_days"),
                "weather_forecast_days": forecast_meta.get("weather_forecast_days"),
                "s_index_considered_days": considered_days,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ha/water_today", methods=["GET"])
def ha_water_today():
    """Return today's water heater energy usage from HA or sqlite fallback."""
    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)

        ha_config = load_home_assistant_config()
        # Read entity ID from config.yaml
        input_sensors = config.get("input_sensors", {})
        entity_id = input_sensors.get(
            "water_heater_consumption",
            ha_config.get("water_heater_daily_entity_id", "sensor.vvb_energy_daily"),
        )

        ha_value = get_home_assistant_sensor_float(entity_id) if entity_id else None

        if ha_value is not None:
            return jsonify({"source": "home_assistant", "water_kwh_today": round(ha_value, 2)})

        learning_cfg = config.get("learning", {})
        sqlite_path = learning_cfg.get("sqlite_path", "data/planner_learning.db")
        timezone_name = config.get("timezone", "Europe/Stockholm")
        tz = pytz.timezone(timezone_name)
        today_key = datetime.now(tz).date().isoformat()

        if os.path.exists(sqlite_path):
            with sqlite3.connect(sqlite_path) as conn:
                cur = conn.execute(
                    "SELECT used_kwh FROM daily_water WHERE date = ?",
                    (today_key,),
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    return jsonify({"source": "sqlite", "water_kwh_today": round(float(row[0]), 2)})

        return jsonify({"source": "unknown", "water_kwh_today": None})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/simulate", methods=["POST"])
def simulate():
    logger.info("--- SIMULATION ENDPOINT TRIGGERED ---")
    try:
        # Step A: Get a base DataFrame with all necessary data
        input_data = get_all_input_data()
        # Load config manually
        with open("config.yaml", "r") as f:
            config_data = yaml.safe_load(f)
        # --- REV 21 CHANGE: Handle Overrides ---
        payload = request.get_json(silent=True) or {}
        manual_plan_payload = payload.get("manual_plan")

        if "manual_plan" not in payload and "overrides" not in payload:
            manual_plan_payload = payload
            overrides = {}
        else:
            overrides = payload.get("overrides", {})

        # Apply overrides to config_data (Deep Merge)
        if overrides:

            def deep_merge(target, source):
                for k, v in source.items():
                    if k in target and isinstance(target[k], dict) and isinstance(v, dict):
                        deep_merge(target[k], v)
                    else:
                        target[k] = v

            deep_merge(config_data, overrides)
            logger.info(f"Simulating with overrides: {overrides}")
        # ---------------------------------------

        initial_state = input_data["initial_state"]

        if "battery" in overrides and "capacity_kwh" in overrides["battery"]:
            try:
                new_cap = float(overrides["battery"]["capacity_kwh"])
                current_soc_pct = initial_state.get("battery_soc_percent", 0)
                initial_state["battery_kwh"] = (current_soc_pct / 100.0) * new_cap
            except (TypeError, ValueError):
                logger.warning("Invalid battery.capacity_kwh override, skipping capacity scaling.")

        df = prepare_df(input_data, tz_name=config_data.get("timezone", "Europe/Stockholm"))
        df = apply_manual_plan(df, manual_plan_payload, config_data)

        if df.empty:
            logger.warning(
                "Simulation aborted: no schedule slots available after applying manual plan."
            )
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Unable to simulate because no input slots are available. "
                        "Please try again later when new price/forecast data is present.",
                    }
                ),
                400,
            )

        logger.info("Running simulation with the user's manual plan...")
        simulated_df = simulate_schedule(df, config_data, initial_state)
        logger.info("Simulation completed successfully.")

        # Step E: Persist and return the full, simulated result WITH preserved history
        json_response = dataframe_to_json_response(simulated_df)

        # --- Preserve historical slots (reuse logic from save endpoint) ---
        try:
            from db_writer import get_preserved_slots
            import pytz as _pytz

            tz = _pytz.timezone("Europe/Stockholm")
            now = datetime.now(tz)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

            secrets = _load_yaml("secrets.yaml")
            existing_past_slots = get_preserved_slots(
                today_start,
                now,
                secrets,
                tz_name=tz.zone if hasattr(tz, "zone") else "Europe/Stockholm",
            )

            # Continue slot_number from the preserved past
            max_hist_slot = max([s.get("slot_number", 0) for s in existing_past_slots], default=0)
            for i, rec in enumerate(json_response):
                rec["slot_number"] = max_hist_slot + i + 1

            merged_schedule = existing_past_slots + json_response
        except Exception as _e:
            logger.warning("Could not preserve historical slots in /api/simulate: %s", _e)
            merged_schedule = json_response

        # Build meta and save
        try:
            version = (
                subprocess.check_output(
                    ["git", "describe", "--tags", "--always", "--dirty"], stderr=subprocess.DEVNULL
                )
                .decode()
                .strip()
            )
        except Exception:
            version = "dev"

        out = {
            "schedule": merged_schedule,
            "meta": {
                "planned_at": datetime.now().isoformat(),
                "planner_version": version,
            },
        }
        with open("schedule.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

        # ✅ Return the merged schedule so the UI keeps history immediately
        return jsonify(out)

    except Exception as e:
        logger.exception("Simulation failed")
        return jsonify({"status": "error", "message": f"Simulation failed: {str(e)}"}), 500


@app.route("/api/learning/status", methods=["GET"])
def learning_status():
    """Return learning engine status and metrics."""
    try:
        engine = get_learning_engine()
        status = engine.get_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/learning/changes", methods=["GET"])
def learning_changes():
    """Return recent learning configuration changes."""
    try:
        engine = get_learning_engine()

        # Get recent config changes
        with sqlite3.connect(engine.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, created_at, reason, applied, metrics_json
                FROM config_versions
                ORDER BY created_at DESC
                LIMIT 10
            """
            )

            changes = []
            for row in cursor.fetchall():
                change = {
                    "id": row[0],
                    "created_at": row[1],
                    "reason": row[2],
                    "applied": bool(row[3]),
                    "metrics": json.loads(row[4]) if row[4] else None,
                }
                changes.append(change)

        return jsonify({"changes": changes})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/learning/run", methods=["POST"])
def learning_run():
    """Trigger learning orchestration manually."""
    try:
        engine = get_learning_engine()
        from learning import NightlyOrchestrator

        orchestrator = NightlyOrchestrator(engine)
        result = orchestrator.run_nightly_job()

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/performance/data", methods=["GET"])
def performance_data():
    """Return performance data for visualization."""
    try:
        days = int(request.args.get("days", 7))
        engine = get_learning_engine()
        data = engine.get_performance_series(days_back=days)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/learning/loops", methods=["GET"])
def learning_loops():
    """Get status of individual learning loops."""
    try:
        engine = get_learning_engine()
        from learning import LearningLoops

        loops = LearningLoops(engine)

        # Test each loop
        results = {}

        # Forecast calibrator
        fc_result = loops.forecast_calibrator()
        results["forecast_calibrator"] = {
            "status": "has_changes" if fc_result else "no_changes",
            "result": fc_result,
        }

        # Threshold tuner
        tt_result = loops.threshold_tuner()
        results["threshold_tuner"] = {
            "status": "has_changes" if tt_result else "no_changes",
            "result": tt_result,
        }

        # S-index tuner
        si_result = loops.s_index_tuner()
        results["s_index_tuner"] = {
            "status": "has_changes" if si_result else "no_changes",
            "result": si_result,
        }

        # Export guard tuner
        eg_result = loops.export_guard_tuner()
        results["export_guard_tuner"] = {
            "status": "has_changes" if eg_result else "no_changes",
            "result": eg_result,
        }

        return jsonify(results)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/forecast/run_eval", methods=["POST"])
def forecast_run_eval():
    """Trigger AURORA evaluation (shadow-mode) for the recent window."""
    try:
        days_back = int(request.json.get("days_back", 7)) if request.is_json else 7
    except Exception:
        days_back = 7

    # Use the same interpreter and ensure repo root is on PYTHONPATH
    python_bin = sys.executable
    cmd = [python_bin, "-m", "ml.evaluate", "--days-back", str(days_back)]
    env = os.environ.copy()
    cwd = os.getcwd()
    env["PYTHONPATH"] = f"{cwd}{os.pathsep}{env.get('PYTHONPATH', '')}"
    try:
        subprocess.check_call(cmd, env=env, cwd=cwd)
        return jsonify({"status": "success", "days_back": days_back})
    except subprocess.CalledProcessError as exc:
        logger.error("forecast_run_eval failed: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route("/api/forecast/run_forward", methods=["POST"])
def forecast_run_forward():
    """Trigger forward AURORA forecast generation for the planner horizon."""
    try:
        horizon_hours = int(request.json.get("horizon_hours", 48)) if request.is_json else 48
    except Exception:
        horizon_hours = 48

    python_bin = sys.executable
    cmd = [python_bin, "-m", "ml.forward"]
    env = os.environ.copy()
    cwd = os.getcwd()
    env["PYTHONPATH"] = f"{cwd}{os.pathsep}{env.get('PYTHONPATH', '')}"
    try:
        subprocess.check_call(cmd, env=env, cwd=cwd)
        return jsonify({"status": "success", "horizon_hours": horizon_hours})
    except subprocess.CalledProcessError as exc:
        logger.error("forecast_run_forward failed: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route("/api/learning/history", methods=["GET"])
def learning_history():
    """Return recent learning runs for history/mini-chart visualisation."""
    try:
        engine = get_learning_engine()
        if not os.path.exists(engine.db_path):
            return jsonify({"runs": []})

        runs: list[dict] = []
        s_index_history: list[dict] = []
        recent_changes: list[dict] = []
        with sqlite3.connect(engine.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, started_at, status, result_metrics_json
                FROM learning_runs
                ORDER BY started_at DESC
                LIMIT 20
                """
            )
            for row in cursor.fetchall():
                run_id, started_at, status, metrics_json = row
                loops_run = None
                changes_proposed = None
                changes_applied = None
                if metrics_json:
                    try:
                        metrics = json.loads(metrics_json)
                        loops_run = metrics.get("loops_run")
                        changes_proposed = metrics.get("changes_proposed")
                        changes_applied = metrics.get("changes_applied")
                    except (TypeError, json.JSONDecodeError):
                        pass

                runs.append(
                    {
                        "id": run_id,
                        "started_at": started_at,
                        "status": status,
                        "loops_run": loops_run,
                        "changes_proposed": changes_proposed,
                        "changes_applied": changes_applied,
                    }
                )

            # Fetch S-index factor history stored in learning_daily_metrics
            cursor.execute(
                """
                SELECT date, s_index_base_factor
                FROM learning_daily_metrics
                WHERE s_index_base_factor IS NOT NULL
                ORDER BY date DESC
                LIMIT 60
                """
            )
            for date_str, value in cursor.fetchall():
                s_index_history.append(
                    {
                        "date": date_str,
                        "metric": "s_index.base_factor",
                        "value": float(value) if value is not None else None,
                    }
                )
            # Fetch recent parameter changes (joined with learning_runs for timestamp)
            cursor.execute(
                """
                SELECT h.run_id,
                       r.started_at,
                       h.param_path,
                       h.old_value,
                       h.new_value,
                       h.loop,
                       h.reason
                FROM learning_param_history h
                LEFT JOIN learning_runs r ON h.run_id = r.id
                ORDER BY h.id DESC
                LIMIT 20
                """
            )
            for row in cursor.fetchall():
                (
                    run_id,
                    started_at,
                    param_path,
                    old_value,
                    new_value,
                    loop_name,
                    reason,
                ) = row
                recent_changes.append(
                    {
                        "run_id": run_id,
                        "started_at": started_at,
                        "param_path": param_path,
                        "old_value": old_value,
                        "new_value": new_value,
                        "loop": loop_name,
                        "reason": reason,
                    }
                )

        return jsonify(
            {"runs": runs, "s_index_history": s_index_history, "recent_changes": recent_changes}
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/learning/daily_metrics", methods=["GET"])
def learning_daily_metrics():
    """Return latest consolidated daily learning metrics (one row per date)."""
    try:
        engine = get_learning_engine()
        if not os.path.exists(engine.db_path):
            return jsonify({"message": "learning DB not found"}), 404

        latest: dict | None = None
        with sqlite3.connect(engine.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT date,
                       pv_error_mean_abs_kwh,
                       load_error_mean_abs_kwh,
                       s_index_base_factor
                FROM learning_daily_metrics
                ORDER BY date DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            if row:
                latest = {
                    "date": row[0],
                    "pv_error_mean_abs_kwh": float(row[1]) if row[1] is not None else None,
                    "load_error_mean_abs_kwh": float(row[2]) if row[2] is not None else None,
                    "s_index_base_factor": float(row[3]) if row[3] is not None else None,
                }

        if not latest:
            return jsonify({"message": "no daily metrics yet"}), 200

        return jsonify(latest)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/debug", methods=["GET"])
def debug_data():
    """Return comprehensive planner debug data from schedule.json."""
    try:
        with open("schedule.json", "r") as f:
            data = json.load(f)

        debug_section = data.get("debug", {})
        if not debug_section:
            return (
                jsonify(
                    {
                        "error": (
                            "No debug data available. "
                            "Enable debug mode in config.yaml with enable_planner_debug: true"
                        )
                    }
                ),
                404,
            )

        return jsonify(debug_section)

    except FileNotFoundError:
        return jsonify({"error": "schedule.json not found. Run the planner first."}), 404


@app.route("/api/debug/logs", methods=["GET"])
def debug_logs():
    """Return recent server logs stored in the ring buffer handler."""
    try:
        return jsonify({"logs": _ring_buffer_handler.get_logs()})
    except Exception as exc:
        logger.exception("Failed to fetch debug logs")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/history/soc", methods=["GET"])
def historic_soc():
    """Return historic SoC data for today from learning database."""
    try:
        date_param = request.args.get("date", "today")

        # Determine target date
        if date_param == "today":
            target_date = datetime.now(pytz.timezone("Europe/Stockholm")).date()
        else:
            try:
                target_date = datetime.strptime(date_param, "%Y-%m-%d").date()
            except ValueError:
                return jsonify({"error": 'Invalid date format. Use YYYY-MM-DD or "today"'}), 400

        # Get learning engine and query historic SoC data
        engine = get_learning_engine()

        with sqlite3.connect(engine.db_path) as conn:
            query = """
                SELECT slot_start, soc_end_percent, quality_flags
                FROM slot_observations
                WHERE DATE(slot_start) = ?
                  AND soc_end_percent IS NOT NULL
                ORDER BY slot_start ASC
            """
            rows = conn.execute(query, (target_date.isoformat(),)).fetchall()

        if not rows:
            return jsonify(
                {
                    "date": target_date.isoformat(),
                    "slots": [],
                    "message": "No historical SoC data available for this date",
                }
            )

        # Convert to JSON format
        slots = []
        for row in rows:
            slots.append(
                {"timestamp": row[0], "soc_percent": row[1], "quality_flags": row[2] or ""}
            )

        return jsonify({"date": target_date.isoformat(), "slots": slots, "count": len(slots)})

    except Exception as e:
        return jsonify({"error": f"Failed to fetch historical SoC data: {str(e)}"}), 500


@app.route("/performance")
def performance_page():
    """Render the performance dashboard."""
    return render_template("performance.html")


@app.route("/api/performance/metrics")
def get_performance_metrics():
    """Get performance metrics for charts."""
    try:
        engine = get_learning_engine()
        days = request.args.get("days", 7, type=int)
        data = engine.get_performance_series(days_back=days)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def record_observation_from_current_state():
    """Record current system state as observation for learning engine."""
    try:
        from backend.learning import get_learning_engine
        import pandas as pd
        from datetime import datetime, timedelta
        import pytz

        engine = get_learning_engine()
        if not engine.learning_config.get("enable", False):
            return  # Learning disabled

        # Get current time in local timezone
        tz = pytz.timezone(engine.config.get("timezone", "Europe/Stockholm"))
        now = datetime.now(tz)

        # Get current system state
        try:
            from inputs import get_initial_state, get_nordpool_data

            initial_state = get_initial_state()

            if not initial_state:
                return  # No data available

            # Fetch current prices
            try:
                price_data = get_nordpool_data()
                current_import_price = 0.0
                current_export_price = 0.0

                # Find price for current slot
                # We use current_slot_start which is timezone-aware (from now)
                # price_data slots are also timezone-aware
                for slot in price_data:
                    if slot["start_time"] <= now < slot["end_time"]:
                        current_import_price = slot["import_price_sek_kwh"]
                        current_export_price = slot["export_price_sek_kwh"]
                        break
            except Exception as e:
                logger.warning(f"Failed to fetch current prices: {e}")
                current_import_price = 0.0
                current_export_price = 0.0

            # Create observation record aligned to 15-minute slots
            current_slot_start = now.replace(
                minute=(now.minute // 15) * 15, second=0, microsecond=0
            )
            current_slot_end = current_slot_start + timedelta(minutes=15)

            # Check if observation already exists for this slot
            with sqlite3.connect(engine.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    (
                        "SELECT COUNT(*) FROM slot_observations "
                        "WHERE slot_start = ? AND soc_end_percent IS NOT NULL"
                    ),
                    (current_slot_start.isoformat(),),
                )
                existing_count = cursor.fetchone()[0]

            if existing_count > 0:
                logger.info(
                    "[learning] Observation already exists for slot %s",
                    current_slot_start.isoformat(),
                )
                return  # Skip if already recorded

            # Fetch cumulative energy sensors from Home Assistant
            # These are total-increasing kWh counters on the inverter.
            sensor_totals = {
                "pv_total": get_home_assistant_sensor_float("sensor.inverter_total_production"),
                "load_total": get_home_assistant_sensor_float(
                    "sensor.inverter_total_load_consumption"
                ),
                "grid_import_total": get_home_assistant_sensor_float(
                    "sensor.inverter_total_energy_import"
                ),
                "grid_export_total": get_home_assistant_sensor_float(
                    "sensor.inverter_total_energy_export"
                ),
                "battery_charge_total": get_home_assistant_sensor_float(
                    "sensor.inverter_total_battery_charge"
                ),
                "battery_discharge_total": get_home_assistant_sensor_float(
                    "sensor.inverter_total_battery_discharge"
                ),
            }

            # Compute deltas vs last recorded totals
            deltas = {
                "pv_kwh": 0.0,
                "load_kwh": 0.0,
                "import_kwh": 0.0,
                "export_kwh": 0.0,
                "batt_charge_kwh": 0.0,
                "batt_discharge_kwh": 0.0,
            }

            with sqlite3.connect(engine.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sensor_totals (
                        name TEXT PRIMARY KEY,
                        last_value REAL,
                        last_timestamp TEXT
                    )
                    """
                )

                for name, value in sensor_totals.items():
                    if value is None:
                        continue
                    cursor.execute("SELECT last_value FROM sensor_totals WHERE name = ?", (name,))
                    row = cursor.fetchone()
                    if row is None:
                        # First observation for this sensor – initialise without delta
                        delta = 0.0
                        cursor.execute(
                            "INSERT INTO sensor_totals (name, last_value, last_timestamp) "
                            "VALUES (?, ?, ?)",
                            (name, float(value), now.isoformat()),
                        )
                    else:
                        last_value = float(row[0])
                        raw_delta = float(value) - last_value
                        delta = max(0.0, raw_delta)
                        cursor.execute(
                            "UPDATE sensor_totals SET last_value = ?, last_timestamp = ? "
                            "WHERE name = ?",
                            (float(value), now.isoformat(), name),
                        )

                    if name == "pv_total":
                        deltas["pv_kwh"] = delta
                    elif name == "load_total":
                        deltas["load_kwh"] = delta
                    elif name == "grid_import_total":
                        deltas["import_kwh"] = delta
                    elif name == "grid_export_total":
                        deltas["export_kwh"] = delta
                    elif name == "battery_charge_total":
                        deltas["batt_charge_kwh"] = delta
                    elif name == "battery_discharge_total":
                        deltas["batt_discharge_kwh"] = delta

                conn.commit()

            observation = {
                "slot_start": current_slot_start.isoformat(),
                "slot_end": current_slot_end.isoformat(),
                "import_kwh": deltas["import_kwh"],
                "export_kwh": deltas["export_kwh"],
                "pv_kwh": deltas["pv_kwh"],
                "load_kwh": deltas["load_kwh"],
                "water_kwh": 0.0,
                "batt_charge_kwh": deltas["batt_charge_kwh"],
                "batt_discharge_kwh": deltas["batt_discharge_kwh"],
                "soc_start_percent": initial_state.get("battery_soc_percent", 0),
                "soc_end_percent": initial_state.get("battery_soc_percent", 0),
                "import_price_sek_kwh": current_import_price,
                "export_price_sek_kwh": current_export_price,
                "quality_flags": "auto_recorded",
            }

            # Create DataFrame and store observation
            observations_df = pd.DataFrame([observation])
            engine.store_slot_observations(observations_df)
            logger.info(
                "[learning] Recorded observation for slot %s: soc=%s%%, "
                "import=%.3f kWh, export=%.3f kWh, pv=%.3f kWh, load=%.3f kWh",
                current_slot_start.isoformat(),
                initial_state.get("battery_soc_percent", 0),
                deltas["import_kwh"],
                deltas["export_kwh"],
                deltas["pv_kwh"],
                deltas["load_kwh"],
            )

        except Exception:
            logger.exception("Failed to record learning observation")

    except Exception:
        logger.exception("Error in record_observation_from_current_state")


@app.route("/api/learning/record_observation", methods=["POST"])
def record_observation():
    """Trigger observation recording from current system state."""
    try:
        record_observation_from_current_state()
        return jsonify({"status": "success", "message": "Observation recorded"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# Set up automatic observation recording
def setup_auto_observation_recording():
    """Set up automatic observation recording every 15 minutes."""

    def record_observation_loop():
        while True:
            try:
                record_observation_from_current_state()
            except Exception:
                logger.exception("Error in automatic observation recording loop")
            # Sleep for 15 minutes (900 seconds)
            import time

            time.sleep(900)

    # Start the recording thread
    recording_thread = threading.Thread(target=record_observation_loop, daemon=True)
    recording_thread.start()
    logger.info("Started automatic observation recording thread")


@app.route("/debug-log", methods=["POST"])
def debug_log():
    """Receive debug logs from browser for troubleshooting."""
    try:
        data = request.get_json()
        message = data.get("message", "")
        timestamp = data.get("timestamp", "")

        # Log to console and file
        log_message = f"[Browser Debug] {timestamp}: {message}"
        logger.info(log_message)

        # Also append to debug log file
        with open("browser_debug.log", "a") as f:
            f.write(log_message + "\n")

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Start automatic recording when webapp starts
setup_auto_observation_recording()


# Auto-start executor background loop if enabled in config
def _autostart_executor():
    """Start the executor background loop if enabled in config."""
    try:
        config = _load_yaml("config.yaml")
        executor_cfg = config.get("executor", {})
        if executor_cfg.get("enabled", False):
            executor = _get_executor()
            if executor:
                logger.info("Auto-starting executor background loop (enabled in config)")
                executor.start()
    except Exception as e:
        logger.warning("Failed to auto-start executor: %s", e)


_autostart_executor()
