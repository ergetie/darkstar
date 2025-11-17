from __future__ import annotations

from datetime import datetime
from typing import Dict

import pandas as pd
import pytz
import requests
import yaml

from inputs import _make_ha_headers, load_home_assistant_config


def _load_config(config_path: str = "config.yaml") -> Dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_vacation_mode_series(
    start_time: datetime,
    end_time: datetime,
    config: Dict | None = None,
    *,
    config_path: str = "config.yaml",
) -> pd.Series:
    """
    Fetch historic vacation_mode state as a 15-minute series (1.0 on, 0.0 off).

    Returns a Series indexed by tz-aware datetimes in the planner timezone.
    If anything fails (no config, no HA, no data), returns an empty Series.
    """
    cfg = config or _load_config(config_path)
    tz = pytz.timezone(cfg.get("timezone", "Europe/Stockholm"))
    sensors = cfg.get("input_sensors", {}) or {}
    entity_id = sensors.get("vacation_mode")
    if not entity_id:
        return pd.Series(dtype="float32")

    ha_cfg = load_home_assistant_config()
    url = ha_cfg.get("url")
    token = ha_cfg.get("token")
    if not url or not token:
        return pd.Series(dtype="float32")

    headers = _make_ha_headers(token)
    api_url = f"{url.rstrip('/')}/api/history/period/{start_time.isoformat()}"
    params = {
        "filter_entity_id": entity_id,
        "end_time": end_time.isoformat(),
        "significant_changes_only": False,
        "minimal_response": False,
    }

    try:
        resp = requests.get(api_url, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return pd.Series(dtype="float32")

    if not data or not data[0]:
        return pd.Series(dtype="float32")

    states = data[0]
    records: list[tuple[datetime, float]] = []
    for state in states:
        ts_str = state.get("last_changed") or state.get("last_updated")
        raw = (state.get("state") or "").lower()
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except Exception:
            continue
        if ts.tzinfo is None:
            ts = pytz.UTC.localize(ts)
        value = 1.0 if raw == "on" else 0.0
        records.append((ts, value))

    if not records:
        return pd.Series(dtype="float32")

    df = pd.DataFrame(records, columns=["timestamp", "value"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    df["timestamp"] = df["timestamp"].dt.tz_convert(tz)
    df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")

    # Build 15-minute slots in local time
    start_local = start_time.astimezone(tz)
    end_local = end_time.astimezone(tz)
    slots = pd.date_range(
        start=start_local,
        end=end_local,
        freq="15min",
        tz=tz,
    )
    base = df.set_index("timestamp")["value"]
    series = base.reindex(slots).ffill().astype("float32")

    return series[(series.index >= start_local) & (series.index < end_local)]


def get_alarm_armed_series(
    start_time: datetime,
    end_time: datetime,
    config: Dict | None = None,
    *,
    config_path: str = "config.yaml",
) -> pd.Series:
    """
    Fetch historic alarm armed state as a 15-minute series (1.0 armed, 0.0 disarmed).

    Uses the `input_sensors.alarm_state` entity (e.g. alarm_control_panel.alarmo).
    """
    cfg = config or _load_config(config_path)
    tz = pytz.timezone(cfg.get("timezone", "Europe/Stockholm"))
    sensors = cfg.get("input_sensors", {}) or {}
    entity_id = sensors.get("alarm_state")
    if not entity_id:
        return pd.Series(dtype="float32")

    ha_cfg = load_home_assistant_config()
    url = ha_cfg.get("url")
    token = ha_cfg.get("token")
    if not url or not token:
        return pd.Series(dtype="float32")

    headers = _make_ha_headers(token)
    api_url = f"{url.rstrip('/')}/api/history/period/{start_time.isoformat()}"
    params = {
        "filter_entity_id": entity_id,
        "end_time": end_time.isoformat(),
        "significant_changes_only": False,
        "minimal_response": False,
    }

    try:
        resp = requests.get(api_url, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return pd.Series(dtype="float32")

    if not data or not data[0]:
        return pd.Series(dtype="float32")

    states = data[0]
    records: list[tuple[datetime, float]] = []
    for state in states:
        ts_str = state.get("last_changed") or state.get("last_updated")
        raw = (state.get("state") or "").lower()
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except Exception:
            continue
        if ts.tzinfo is None:
            ts = pytz.UTC.localize(ts)
        # Treat anything other than 'disarmed' as armed
        value = 0.0 if raw == "disarmed" else 1.0
        records.append((ts, value))

    if not records:
        return pd.Series(dtype="float32")

    df = pd.DataFrame(records, columns=["timestamp", "value"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    df["timestamp"] = df["timestamp"].dt.tz_convert(tz)
    df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")

    start_local = start_time.astimezone(tz)
    end_local = end_time.astimezone(tz)
    slots = pd.date_range(
        start=start_local,
        end=end_local,
        freq="15min",
        tz=tz,
    )
    base = df.set_index("timestamp")["value"]
    series = base.reindex(slots).ffill().astype("float32")

    return series[(series.index >= start_local) & (series.index < end_local)]
