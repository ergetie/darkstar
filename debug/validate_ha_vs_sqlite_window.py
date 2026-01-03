import argparse
import asyncio
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import pytz
import yaml

try:
    import websockets  # type: ignore
except ImportError:  # pragma: no cover - runtime dependency only
    websockets = None


DEFAULT_TOLERANCE_KWH = 0.2


@dataclass
class DayQualitySummary:
    date: str
    status: str
    bad_hours_load: int = 0
    bad_hours_pv: int = 0
    bad_hours_import: int = 0
    bad_hours_export: int = 0
    bad_hours_batt: int = 0
    missing_slots: int = 0
    soc_issues: int = 0
    metadata_json: str = ""


def load_config() -> dict[str, Any]:
    with open("config.yaml", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_secrets() -> dict[str, Any]:
    with open("secrets.yaml", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def resolve_db_path(config: dict[str, Any]) -> str:
    learning_cfg = config.get("learning") or {}
    return learning_cfg.get("sqlite_path") or "data/planner_learning.db"


def parse_date(value: str) -> date:
    try:
        return datetime.fromisoformat(value).date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Dates must be ISO formatted (YYYY-MM-DD)") from exc


def build_channel_set(raw: str | None) -> set[str]:
    """
    Parse --channels argument into a canonical set.

    Supported canonical names:
        load, pv, import, export, batt, batt_charge, batt_discharge
    """
    base = {"load", "pv", "import", "export", "batt_charge", "batt_discharge"}
    if not raw:
        return base

    tokens = {token.strip().lower() for token in raw.split(",") if token.strip()}
    result: set[str] = set()
    for token in tokens:
        if token == "batt":
            result.add("batt_charge")
            result.add("batt_discharge")
        elif token in base:
            result.add(token)
    return result or base


def ensure_data_quality_table(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS data_quality_daily (
            date TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            bad_hours_load INTEGER DEFAULT 0,
            bad_hours_pv INTEGER DEFAULT 0,
            bad_hours_import INTEGER DEFAULT 0,
            bad_hours_export INTEGER DEFAULT 0,
            bad_hours_batt INTEGER DEFAULT 0,
            missing_slots INTEGER DEFAULT 0,
            soc_issues INTEGER DEFAULT 0,
            metadata_json TEXT
        )
        """
    )
    conn.commit()


def persist_day_summary(conn: sqlite3.Connection, summary: DayQualitySummary) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO data_quality_daily (
            date,
            status,
            bad_hours_load,
            bad_hours_pv,
            bad_hours_import,
            bad_hours_export,
            bad_hours_batt,
            missing_slots,
            soc_issues,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            status = excluded.status,
            bad_hours_load = excluded.bad_hours_load,
            bad_hours_pv = excluded.bad_hours_pv,
            bad_hours_import = excluded.bad_hours_import,
            bad_hours_export = excluded.bad_hours_export,
            bad_hours_batt = excluded.bad_hours_batt,
            missing_slots = excluded.missing_slots,
            soc_issues = excluded.soc_issues,
            metadata_json = excluded.metadata_json
        """,
        (
            summary.date,
            summary.status,
            summary.bad_hours_load,
            summary.bad_hours_pv,
            summary.bad_hours_import,
            summary.bad_hours_export,
            summary.bad_hours_batt,
            summary.missing_slots,
            summary.soc_issues,
            summary.metadata_json,
        ),
    )
    conn.commit()


def fetch_sqlite_slots_for_day(
    conn: sqlite3.Connection,
    target_day: date,
) -> list[dict[str, Any]]:
    """
    Fetch all slot_observations rows for a local calendar day.

    slot_start is stored as local ISO with timezone (YYYY-MM-DDTHH:MM:SS+HH:MM),
    so we can safely filter by prefix on the date component.
    """
    prefix = target_day.isoformat()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            slot_start,
            load_kwh,
            pv_kwh,
            import_kwh,
            export_kwh,
            batt_charge_kwh,
            batt_discharge_kwh,
            soc_start_percent,
            soc_end_percent
        FROM slot_observations
        WHERE slot_start LIKE ?
        ORDER BY slot_start
        """,
        (f"{prefix}%",),
    )
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]


def aggregate_sqlite_hourly(
    slots: list[dict[str, Any]],
    tz: pytz.BaseTzInfo,
) -> tuple[dict[str, dict[int, float]], int, int]:
    """
    Aggregate slot-level energy into per-hour sums for each channel.

    Returns:
        hourly: channel -> hour -> kWh
        missing_slots: number of slots with missing core energy values
        soc_issues: number of slots with obvious SoC anomalies
    """
    hourly: dict[str, dict[int, float]] = {
        "load": defaultdict(float),
        "pv": defaultdict(float),
        "import": defaultdict(float),
        "export": defaultdict(float),
        "batt_charge": defaultdict(float),
        "batt_discharge": defaultdict(float),
    }
    missing_slots = 0
    soc_issues = 0

    previous_soc_end: float | None = None
    previous_time: datetime | None = None

    for row in slots:
        slot_start_str = row.get("slot_start")
        if not slot_start_str:
            continue
        try:
            dt = datetime.fromisoformat(slot_start_str)
            dt = tz.localize(dt) if dt.tzinfo is None else dt.astimezone(tz)
        except Exception:
            # If parsing fails, skip this slot but count as missing.
            missing_slots += 1
            continue

        hour = dt.hour

        # Energy aggregation
        for channel, key in (
            ("load", "load_kwh"),
            ("pv", "pv_kwh"),
            ("import", "import_kwh"),
            ("export", "export_kwh"),
            ("batt_charge", "batt_charge_kwh"),
            ("batt_discharge", "batt_discharge_kwh"),
        ):
            value = row.get(key)
            if value is None:
                # Only count missing for core flows
                if channel in {"load", "pv", "import", "export"}:
                    missing_slots += 1
                continue
            try:
                hourly[channel][hour] += float(value)
            except (TypeError, ValueError):
                if channel in {"load", "pv", "import", "export"}:
                    missing_slots += 1

        # SoC sanity checks
        soc_start = row.get("soc_start_percent")
        soc_end = row.get("soc_end_percent")
        try:
            soc_start_f = float(soc_start) if soc_start is not None else None
            soc_end_f = float(soc_end) if soc_end is not None else None
        except (TypeError, ValueError):
            soc_start_f = None
            soc_end_f = None

        for val in (soc_start_f, soc_end_f):
            if val is not None and (val < 0.0 or val > 100.0):
                soc_issues += 1

        if soc_start_f is not None and soc_end_f is not None:
            if abs(soc_end_f - soc_start_f) > 40.0:
                soc_issues += 1

        if previous_soc_end is not None and soc_start_f is not None and previous_time is not None:
            delta_minutes = (dt - previous_time).total_seconds() / 60.0
            if delta_minutes <= 30.0 and abs(soc_start_f - previous_soc_end) > 40.0:
                soc_issues += 1

        if soc_end_f is not None:
            previous_soc_end = soc_end_f
            previous_time = dt

    return hourly, missing_slots, soc_issues


async def fetch_ha_statistics_window(
    tz: pytz.BaseTzInfo,
    start_day: date,
    end_day: date,
    channel_entities: dict[str, str],
) -> dict[str, dict[date, dict[int, float]]]:
    """
    Fetch HA LTS statistics for all requested entities over the date window.

    Returns:
        channel -> day -> hour -> kWh
    """
    secrets = load_secrets()
    load_config()

    ha_cfg = secrets.get("home_assistant", {}) or {}
    base_url = (ha_cfg.get("url") or "").rstrip("/")
    token = ha_cfg.get("token")

    if not base_url or not token:
        raise RuntimeError("home_assistant url/token missing in secrets.yaml")

    if websockets is None:
        raise RuntimeError("websockets package is required for HA validation.")

    if base_url.startswith("https://"):
        ws_url = base_url.replace("https://", "wss://") + "/api/websocket"
        use_ssl = True
    else:
        ws_url = base_url.replace("http://", "ws://") + "/api/websocket"
        use_ssl = False

    ssl_context = None
    if use_ssl:
        import ssl as _ssl

        ssl_context = _ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = _ssl.CERT_NONE

    statistic_ids = [entity for entity in channel_entities.values() if entity]
    if not statistic_ids:
        # No HA entities configured; nothing to compare
        return {}

    channel_hourly: dict[str, dict[date, dict[int, float]]] = {
        "load": defaultdict(lambda: defaultdict(float)),
        "pv": defaultdict(lambda: defaultdict(float)),
        "import": defaultdict(lambda: defaultdict(float)),
        "export": defaultdict(lambda: defaultdict(float)),
        "batt_charge": defaultdict(lambda: defaultdict(float)),
        "batt_discharge": defaultdict(lambda: defaultdict(float)),
    }

    # Fetch one day at a time to keep WS frames small.
    async with websockets.connect(ws_url, ssl=ssl_context) as ws:
        # Handshake + auth
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        await ws.recv()

        current = start_day
        msg_id = int(datetime.now(tz=pytz.UTC).timestamp())
        entity_to_channel = {v: k for k, v in channel_entities.items() if v}

        while current <= end_day:
            start_local = datetime.combine(current, datetime.min.time()).replace(tzinfo=tz)
            end_local = start_local + timedelta(days=1)
            start_utc = start_local.astimezone(pytz.UTC)
            end_utc = end_local.astimezone(pytz.UTC)

            msg_id += 1
            msg = {
                "id": msg_id,
                "type": "recorder/statistics_during_period",
                "start_time": start_utc.isoformat().replace("+00:00", "Z"),
                "end_time": end_utc.isoformat().replace("+00:00", "Z"),
                "statistic_ids": statistic_ids,
                "period": "hour",
            }
            await ws.send(json.dumps(msg))
            raw = await ws.recv()
            resp = json.loads(raw)
            result = resp.get("result") or {}

            for entity_id, points in result.items():
                channel = entity_to_channel.get(entity_id)
                if not channel:
                    continue
                for point in points or []:
                    ts_ms = point.get("start")
                    if ts_ms is None:
                        continue
                    try:
                        ts = float(ts_ms) / 1000.0
                    except (TypeError, ValueError):
                        continue
                    dt_utc = datetime.fromtimestamp(ts, pytz.UTC)
                    dt_local = dt_utc.astimezone(tz)
                    day = dt_local.date()
                    if day < start_day or day > end_day:
                        continue
                    hour = dt_local.hour
                    change = point.get("change")
                    if change is None:
                        continue
                    try:
                        change_f = float(change)
                    except (TypeError, ValueError):
                        continue
                    channel_hourly[channel][day][hour] += change_f

            current += timedelta(days=1)

    return channel_hourly


def classify_day(
    day: date,
    tolerance_kwh: float,
    sqlite_hourly: dict[str, dict[int, float]],
    ha_hourly: dict[str, dict[date, dict[int, float]]],
    missing_slots: int,
    soc_issues: int,
    active_channels: set[str],
) -> DayQualitySummary:
    """
    Compare SQLite vs HA per-hour data and derive a day-level quality label.
    """
    core_channels = {"load", "pv", "import", "export"}
    core_channels &= active_channels

    bad_hours: dict[str, int] = {
        "load": 0,
        "pv": 0,
        "import": 0,
        "export": 0,
        "batt": 0,
    }
    flagged_hours_detail: dict[str, list[tuple[int, float, float, float]]] = {}

    # Core channels: compare SQLite vs HA where both sides exist
    for channel in core_channels:
        sqlite_series = sqlite_hourly.get(channel, {})
        ha_series = (ha_hourly.get(channel) or {}).get(day, {})
        for hour in range(24):
            if hour not in sqlite_series and hour not in ha_series:
                continue
            sqlite_val = float(sqlite_series.get(hour, 0.0))
            ha_val = float(ha_series.get(hour, 0.0))
            diff = abs(sqlite_val - ha_val)
            if diff > tolerance_kwh:
                bad_hours[channel] += 1
                key = f"{channel}_hours"
                flagged_hours_detail.setdefault(key, []).append((hour, sqlite_val, ha_val, diff))

    # Battery channels are advisory and only affect mask_battery
    batt_channels = {"batt_charge", "batt_discharge"} & active_channels
    for channel in batt_channels:
        sqlite_series = sqlite_hourly.get(channel, {})
        ha_series = (ha_hourly.get(channel) or {}).get(day, {})
        for hour in range(24):
            if hour not in sqlite_series and hour not in ha_series:
                continue
            sqlite_val = float(sqlite_series.get(hour, 0.0))
            ha_val = float(ha_series.get(hour, 0.0))
            diff = abs(sqlite_val - ha_val)
            if diff > tolerance_kwh:
                bad_hours["batt"] += 1
                key = "batt_hours"
                flagged_hours_detail.setdefault(key, []).append((hour, sqlite_val, ha_val, diff))

    core_bad_total = bad_hours["load"] + bad_hours["pv"] + bad_hours["import"] + bad_hours["export"]

    # Classification rules:
    # - Exclude if slots are missing, SoC is broken, or many core hours are off.
    # - Otherwise keep the day; if only battery is bad, mark for battery masking.
    if missing_slots > 0 or soc_issues > 0 or core_bad_total >= 3:
        status = "exclude"
    else:
        status = "clean"
        if bad_hours["batt"] > 0:
            status = "mask_battery"

    metadata: dict[str, Any] = {
        "tolerance_kwh": tolerance_kwh,
        "core_bad_total": core_bad_total,
        "bad_hours": bad_hours,
    }
    if flagged_hours_detail:
        metadata["flagged_hours_detail"] = flagged_hours_detail

    summary = DayQualitySummary(
        date=day.isoformat(),
        status=status,
        bad_hours_load=bad_hours["load"],
        bad_hours_pv=bad_hours["pv"],
        bad_hours_import=bad_hours["import"],
        bad_hours_export=bad_hours["export"],
        bad_hours_batt=bad_hours["batt"],
        missing_slots=missing_slots,
        soc_issues=soc_issues,
        metadata_json=json.dumps(metadata, ensure_ascii=False),
    )
    return summary


async def main_async(args: argparse.Namespace) -> int:
    config = load_config()
    tz_name = config.get("timezone", "Europe/Stockholm")
    tz = pytz.timezone(tz_name)

    db_path = resolve_db_path(config)

    channels = build_channel_set(args.channels)

    # Map canonical channels to HA entities from input_sensors.
    sensors = config.get("input_sensors", {}) or {}
    channel_entities: dict[str, str] = {}
    if "load" in channels:
        channel_entities["load"] = sensors.get("total_load_consumption")
    if "pv" in channels:
        channel_entities["pv"] = sensors.get("total_pv_production")
    if "import" in channels:
        channel_entities["import"] = sensors.get("total_grid_import")
    if "export" in channels:
        channel_entities["export"] = sensors.get("total_grid_export")
    if "batt_charge" in channels:
        channel_entities["batt_charge"] = sensors.get("total_battery_charge")
    if "batt_discharge" in channels:
        channel_entities["batt_discharge"] = sensors.get("total_battery_discharge")

    start_day: date = args.start_date
    end_day: date = args.end_date
    if end_day < start_day:
        raise SystemExit("end-date must be on or after start-date")

    print(
        f"[validation] Window {start_day.isoformat()} → {end_day.isoformat()}, "
        f"tolerance={args.tolerance_kwh} kWh, channels={sorted(channels)}"
    )
    print(f"[validation] Using SQLite database at {db_path}")

    with sqlite3.connect(db_path, timeout=30.0) as conn:
        ensure_data_quality_table(conn)

    # Fetch HA statistics for the entire window in a single call, if possible.
    try:
        ha_hourly = await fetch_ha_statistics_window(
            tz=tz,
            start_day=start_day,
            end_day=end_day,
            channel_entities=channel_entities,
        )
    except Exception as exc:
        print(f"[validation] Error fetching HA statistics: {exc}")
        print(
            "[validation] Aborting without writing data_quality_daily; "
            "please ensure Home Assistant is reachable and retry."
        )
        return 1

    total_days = (end_day - start_day).days + 1
    clean_days = 0
    masked_days = 0
    excluded_days = 0

    with sqlite3.connect(db_path, timeout=30.0) as conn:
        ensure_data_quality_table(conn)

        for offset in range(total_days):
            day = start_day + timedelta(days=offset)
            slots = fetch_sqlite_slots_for_day(conn, day)
            if not slots:
                summary = DayQualitySummary(
                    date=day.isoformat(),
                    status="exclude",
                    missing_slots=96,
                    metadata_json=json.dumps({"reason": "no_slots_for_day"}, ensure_ascii=False),
                )
                persist_day_summary(conn, summary)
                excluded_days += 1
                print(f"{day}: exclude (no slots)")
                continue

            sqlite_hourly, missing_slots, soc_issues = aggregate_sqlite_hourly(slots, tz)

            summary = classify_day(
                day=day,
                tolerance_kwh=args.tolerance_kwh,
                sqlite_hourly=sqlite_hourly,
                ha_hourly=ha_hourly,
                missing_slots=missing_slots
                + max(0, 96 - len(slots)),  # enforce 96-slot expectation
                soc_issues=soc_issues,
                active_channels=channels,
            )
            persist_day_summary(conn, summary)

            if summary.status == "clean":
                clean_days += 1
            elif summary.status == "mask_battery":
                masked_days += 1
            else:
                excluded_days += 1

            print(
                f"{day}: {summary.status} "
                f"(missing_slots={summary.missing_slots}, "
                f"soc_issues={summary.soc_issues}, "
                f"bad_hours_load={summary.bad_hours_load}, "
                f"bad_hours_pv={summary.bad_hours_pv}, "
                f"bad_hours_import={summary.bad_hours_import}, "
                f"bad_hours_export={summary.bad_hours_export}, "
                f"bad_hours_batt={summary.bad_hours_batt})"
            )

    print(
        "[validation] Summary: "
        f"clean={clean_days}, mask_battery={masked_days}, exclude={excluded_days}, "
        f"days_scanned={total_days}"
    )
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate slot_observations against Home Assistant LTS over a date window "
            "and persist per-day quality classifications into data_quality_daily."
        )
    )
    parser.add_argument(
        "--start-date",
        required=True,
        type=parse_date,
        help="Start date (YYYY-MM-DD, local calendar day).",
    )
    parser.add_argument(
        "--end-date",
        required=True,
        type=parse_date,
        help="End date (YYYY-MM-DD, inclusive, local calendar day).",
    )
    parser.add_argument(
        "--tolerance-kwh",
        type=float,
        default=DEFAULT_TOLERANCE_KWH,
        help="Absolute hourly tolerance |DB − HA| in kWh (default 0.2).",
    )
    parser.add_argument(
        "--channels",
        type=str,
        default="load,pv,import,export,batt_charge,batt_discharge",
        help=(
            "Comma-separated list of channels to validate. "
            "Supported: load,pv,import,export,batt,batt_charge,batt_discharge."
        ),
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    exit_code = asyncio.run(main_async(args))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
