from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import sqlite3

from backend.learning import LearningEngine


@dataclass
class AntaresSlotRecord:
    """
    Single-slot record for Antares v1 training.

    This is a thin, typed wrapper around the underlying dict returned by
    `build_antares_training_dataset`.
    """

    episode_id: str
    episode_date: str
    system_id: str
    data_quality_status: str
    slot_start: str
    import_price_sek_kwh: float
    export_price_sek_kwh: float
    load_kwh: float
    pv_kwh: float
    import_kwh: float
    export_kwh: float
    batt_charge_kwh: Optional[float]
    batt_discharge_kwh: Optional[float]
    soc_start_percent: Optional[float]
    soc_end_percent: Optional[float]
    battery_masked: bool


def _get_engine(config_path: str = "config.yaml") -> LearningEngine:
    """
    Create a fresh LearningEngine for offline dataset extraction.
    """
    return LearningEngine(config_path)


def _load_data_quality(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    Load data_quality_daily into a DataFrame indexed by date.
    """
    df = pd.read_sql_query(
        "SELECT date, status FROM data_quality_daily",
        conn,
    )
    if df.empty:
        return df
    df = df.rename(columns={"date": "episode_date", "status": "data_quality_status"})
    return df


def _load_simulation_episodes(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    Load simulation episodes (system_id=\"simulation\") from training_episodes.
    """
    df = pd.read_sql_query(
        """
        SELECT
            episode_id,
            created_at,
            inputs_json,
            context_json,
            schedule_json
        FROM training_episodes
        WHERE context_json LIKE '%"system_id": "simulation"%'
        """,
        conn,
    )
    if df.empty:
        return df

    def _extract_context(row: pd.Series) -> pd.Series:
        import json

        try:
            ctx = json.loads(row["context_json"] or "{}")
        except Exception:
            ctx = {}
        return pd.Series(
            {
                "episode_date": ctx.get("episode_date"),
                "episode_start_local": ctx.get("episode_start_local"),
                "system_id": ctx.get("system_id", "simulation"),
                "data_quality_status": ctx.get("data_quality_status", "unknown"),
            }
        )

    ctx_df = df.apply(_extract_context, axis=1)
    df = pd.concat([df[["episode_id", "created_at"]], ctx_df], axis=1)
    return df


def _expand_episode_schedule(
    conn: sqlite3.Connection,
    episodes: pd.DataFrame,
    quality: pd.DataFrame,
) -> pd.DataFrame:
    """
    Expand simulation episodes into per-slot schedule rows and join data quality.
    """
    import json

    rows: List[Dict[str, Any]] = []
    for _, ep in episodes.iterrows():
        episode_id = ep["episode_id"]
        episode_date = ep.get("episode_date")
        system_id = ep.get("system_id", "simulation")
        data_quality_status = ep.get("data_quality_status", "unknown")

        # Pull full schedule_json for this episode
        cur = conn.cursor()
        cur.execute(
            """
            SELECT schedule_json
            FROM training_episodes
            WHERE episode_id = ?
            """,
            (episode_id,),
        )
        row = cur.fetchone()
        if not row:
            continue
        (sched_json_str,) = row
        try:
            sched = json.loads(sched_json_str or "{}").get("schedule") or []
        except Exception:
            sched = []

        for slot in sched:
            slot_start = slot.get("start_time")
            if not slot_start:
                continue
            rows.append(
                {
                    "episode_id": episode_id,
                    "episode_date": episode_date,
                    "system_id": system_id,
                    "data_quality_status": data_quality_status,
                    "slot_start": slot_start,
                    "import_price_sek_kwh": float(slot.get("import_price_sek_kwh") or 0.0),
                    "export_price_sek_kwh": float(
                        slot.get("export_price_sek_kwh") or slot.get("import_price_sek_kwh") or 0.0
                    ),
                }
            )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    if not quality.empty:
        df = df.merge(quality, on="episode_date", how="left")
    return df


def build_antares_training_dataset(
    config_path: str = "config.yaml",
    include_mask_battery: bool = True,
) -> List[AntaresSlotRecord]:
    """
    Build a slot-level Antares v1 training dataset from simulation episodes.

    - Sources:
      - SQLite `training_episodes` (system_id=\"simulation\")
      - SQLite `slot_observations`
      - SQLite `data_quality_daily`
    - Contracts:
      - Includes only days where `data_quality_status` is `clean`
        or (optionally) `mask_battery`.
      - Battery flows are masked (set to None, `battery_masked=True`)
        for `mask_battery` days.
    """
    engine = _get_engine(config_path)
    db_path = engine.db_path

    with sqlite3.connect(db_path, timeout=30.0) as conn:
        quality_df = _load_data_quality(conn)
        episodes_df = _load_simulation_episodes(conn)
        if episodes_df.empty:
            return []

        # Filter by quality
        if not quality_df.empty:
            episodes_df = episodes_df.merge(
                quality_df, on="episode_date", how="left", suffixes=("", "_daily")
            )
            # Prefer explicit daily label when present, fall back to episode context.
            if "data_quality_status_daily" in episodes_df.columns:
                episodes_df["data_quality_status"] = episodes_df[
                    "data_quality_status_daily"
                ].fillna(episodes_df["data_quality_status"])
            allowed_status = {"clean"}
            if include_mask_battery:
                allowed_status.add("mask_battery")
            episodes_df = episodes_df[episodes_df["data_quality_status"].isin(allowed_status)]
        if episodes_df.empty:
            return []

        sched_df = _expand_episode_schedule(conn, episodes_df, quality_df)
        if sched_df.empty:
            return []

        # Join slot_observations on slot_start (string equality, local ISO).
        obs_df = pd.read_sql_query(
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
            """,
            conn,
        )

    merged = sched_df.merge(obs_df, on="slot_start", how="left")

    records: List[AntaresSlotRecord] = []
    for row in merged.to_dict("records"):
        status = row.get("data_quality_status") or "unknown"
        battery_masked = bool(status == "mask_battery")

        batt_charge = row.get("batt_charge_kwh")
        batt_discharge = row.get("batt_discharge_kwh")
        if battery_masked:
            batt_charge = None
            batt_discharge = None

        record = AntaresSlotRecord(
            episode_id=str(row.get("episode_id") or ""),
            episode_date=str(row.get("episode_date") or ""),
            system_id=str(row.get("system_id") or "simulation"),
            data_quality_status=status,
            slot_start=str(row.get("slot_start") or ""),
            import_price_sek_kwh=float(row.get("import_price_sek_kwh") or 0.0),
            export_price_sek_kwh=float(row.get("export_price_sek_kwh") or 0.0),
            load_kwh=float(row.get("load_kwh") or 0.0),
            pv_kwh=float(row.get("pv_kwh") or 0.0),
            import_kwh=float(row.get("import_kwh") or 0.0),
            export_kwh=float(row.get("export_kwh") or 0.0),
            batt_charge_kwh=None if batt_charge is None else float(batt_charge),
            batt_discharge_kwh=None if batt_discharge is None else float(batt_discharge),
            soc_start_percent=(
                None
                if row.get("soc_start_percent") is None
                else float(row.get("soc_start_percent"))
            ),
            soc_end_percent=(
                None if row.get("soc_end_percent") is None else float(row.get("soc_end_percent"))
            ),
            battery_masked=battery_masked,
        )
        records.append(record)

    return records
