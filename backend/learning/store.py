import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast as type_cast

import pandas as pd
from sqlalchemy import Integer, case, cast, desc, func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.learning.models import (
    ExecutionLog,
    LearningDailyMetric,
    LearningRun,
    ReflexState,
    SlotForecast,
    SlotObservation,
    SlotPlan,
    SystemState,
    TrainingEpisode,
)

logger = logging.getLogger("darkstar.learning.store")


class LearningStore:
    """
    Handles all database interactions for the Learning Engine using SQLAlchemy.
    """

    def __init__(self, db_path: str, timezone: Any):
        self.db_path = db_path
        self.timezone = timezone

        # Initialize SQLAlchemy Async (ARC10)
        connect_args = {"check_same_thread": False, "timeout": 30.0}
        self.async_engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}", connect_args=connect_args
        )
        self.AsyncSession = async_sessionmaker(self.async_engine, expire_on_commit=False)

        # ARC12: WAL mode will be enabled on first connection
        # (Can't use async in __init__, so we rely on the sync ExecutorHistory
        # or migration script to enable WAL. Once enabled, mode persists.)

    async def close(self):
        """Dispose of the async engine."""
        await self.async_engine.dispose()
        # Prevent aiosqlite _connection_worker_thread from crashing when pytest-asyncio
        # destroys the event loop immediately after tests finish.
        import asyncio

        await asyncio.sleep(0.01)

    async def ensure_wal_mode(self):
        """ARC12: Ensure WAL mode is enabled (idempotent, call once on startup)."""
        async with self.async_engine.begin() as conn:
            await conn.execute(text("PRAGMA journal_mode=WAL"))

    # _init_schema was removed as Alembic handles migrations.

    async def store_slot_prices(self, price_rows: Iterable[dict[str, Any]]) -> None:
        """Store slot price data (import/export SEK per kWh) using Async SQLAlchemy."""
        rows = list(price_rows or [])
        if not rows:
            return

        async with self.AsyncSession() as session:
            for row in rows:
                slot_start: datetime | pd.Timestamp | str | None = row.get("slot_start") or row.get(
                    "start_time"
                )
                slot_end: datetime | pd.Timestamp | str | None = row.get("slot_end") or row.get(
                    "end_time"
                )
                if slot_start is None:
                    continue

                if isinstance(slot_start, datetime | pd.Timestamp):
                    slot_start = slot_start.astimezone(self.timezone).isoformat()
                else:
                    slot_start = pd.to_datetime(slot_start).astimezone(self.timezone).isoformat()

                if slot_end is not None:
                    if isinstance(slot_end, datetime | pd.Timestamp):
                        slot_end = slot_end.astimezone(self.timezone).isoformat()
                    else:
                        slot_end = pd.to_datetime(slot_end).astimezone(self.timezone).isoformat()

                import_price = row.get("import_price_sek_kwh")
                export_price = row.get("export_price_sek_kwh")

                stmt = sqlite_insert(SlotObservation).values(
                    slot_start=slot_start,
                    slot_end=slot_end,
                    import_price_sek_kwh=import_price,
                    export_price_sek_kwh=export_price,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["slot_start"],
                    set_={
                        "slot_end": func.coalesce(stmt.excluded.slot_end, SlotObservation.slot_end),
                        "import_price_sek_kwh": func.coalesce(
                            stmt.excluded.import_price_sek_kwh, SlotObservation.import_price_sek_kwh
                        ),
                        "export_price_sek_kwh": func.coalesce(
                            stmt.excluded.export_price_sek_kwh, SlotObservation.export_price_sek_kwh
                        ),
                    },
                )
                await session.execute(stmt)
            await session.commit()

    async def store_slot_observations(
        self, observations_df: pd.DataFrame, authoritative: bool = True
    ) -> None:
        """Store slot observations in database using Async SQLAlchemy."""
        if observations_df.empty:
            return

        async with self.AsyncSession() as session:
            records = type_cast("list[dict[str, Any]]", observations_df.to_dict("records"))

            for record in records:
                source = "recorder" if authoritative else "backfill"

                def has_measurement(key: str, current_record: dict[str, Any] = record) -> bool:
                    return key in current_record and not pd.isna(current_record.get(key))

                def measured_float(key: str, current_record: dict[str, Any] = record) -> float:
                    if not has_measurement(key):
                        return 0.0
                    return float(current_record[key])

                def quality_flags(
                    current_record: dict[str, Any] = record, current_source: str = source
                ) -> str:
                    # quality_flags is a JSON object; today the recorder only sets
                    # "source". A separate "exclude": true key (added out-of-band by
                    # scripts/flag_january_bad_slots.py, never by this writer) marks a
                    # row as bad for ML training — see ml/train.py's exclusion filter.
                    # It must be preserved, not overwritten, whenever this key merges in.
                    raw_flags = current_record.get("quality_flags", "{}")
                    flags: dict[str, Any]
                    if isinstance(raw_flags, str):
                        try:
                            parsed: Any = json.loads(raw_flags)
                            flags = (
                                type_cast("dict[str, Any]", parsed)
                                if isinstance(parsed, dict)
                                else {}
                            )
                        except json.JSONDecodeError:
                            flags = {}
                    elif isinstance(raw_flags, dict):
                        flags = type_cast("dict[str, Any]", raw_flags)
                    else:
                        flags = {}
                    flags["source"] = current_source
                    return json.dumps(flags, sort_keys=True)

                slot_start_raw: Any = record.get("slot_start")
                slot_end_raw: Any = record.get("slot_end")

                slot_start: str
                if isinstance(slot_start_raw, datetime | pd.Timestamp):
                    slot_start = slot_start_raw.astimezone(self.timezone).isoformat()
                else:
                    slot_start = (  # type: ignore[reportUnknownVariableType]
                        pd.to_datetime(slot_start_raw).astimezone(self.timezone).isoformat()  # type: ignore[reportUnknownMemberType]
                    )

                slot_end: str | None = None
                if slot_end_raw is not None:
                    if isinstance(slot_end_raw, datetime | pd.Timestamp):
                        slot_end = slot_end_raw.astimezone(self.timezone).isoformat()
                    else:
                        slot_end_dt: pd.Timestamp = pd.to_datetime(slot_end_raw)  # type: ignore[reportUnknownMemberType]
                        slot_end = slot_end_dt.astimezone(self.timezone).isoformat()  # type: ignore[reportUnknownMemberType]

                stmt = sqlite_insert(SlotObservation).values(
                    slot_start=slot_start,
                    slot_end=slot_end,
                    import_kwh=measured_float("import_kwh"),
                    export_kwh=measured_float("export_kwh"),
                    pv_kwh=measured_float("pv_kwh"),
                    load_kwh=measured_float("load_kwh"),
                    water_kwh=measured_float("water_kwh"),
                    ev_charging_kwh=measured_float("ev_charging_kwh"),
                    batt_charge_kwh=record.get("batt_charge_kwh"),
                    batt_discharge_kwh=record.get("batt_discharge_kwh"),
                    soc_start_percent=record.get("soc_start_percent"),
                    soc_end_percent=record.get("soc_end_percent"),
                    import_price_sek_kwh=record.get("import_price_sek_kwh"),
                    export_price_sek_kwh=record.get("export_price_sek_kwh"),
                    quality_flags=quality_flags(),
                )

                def energy_update(key: str, column: Any, current_stmt: Any = stmt) -> Any:
                    incoming = getattr(current_stmt.excluded, column.name)
                    if not has_measurement(key):
                        return column
                    if authoritative:
                        return incoming
                    return case(
                        (SlotObservation.quality_flags.like('%"source": "recorder"%'), column),
                        else_=incoming,
                    )

                quality_flags_update = (
                    stmt.excluded.quality_flags
                    if authoritative
                    else func.coalesce(SlotObservation.quality_flags, stmt.excluded.quality_flags)
                )

                stmt = stmt.on_conflict_do_update(
                    index_elements=["slot_start"],
                    set_={
                        "slot_end": func.coalesce(stmt.excluded.slot_end, SlotObservation.slot_end),
                        "import_kwh": energy_update("import_kwh", SlotObservation.import_kwh),
                        "export_kwh": energy_update("export_kwh", SlotObservation.export_kwh),
                        "pv_kwh": energy_update("pv_kwh", SlotObservation.pv_kwh),
                        "load_kwh": energy_update("load_kwh", SlotObservation.load_kwh),
                        "water_kwh": energy_update("water_kwh", SlotObservation.water_kwh),
                        "ev_charging_kwh": energy_update(
                            "ev_charging_kwh", SlotObservation.ev_charging_kwh
                        ),
                        "batt_charge_kwh": func.coalesce(
                            stmt.excluded.batt_charge_kwh, SlotObservation.batt_charge_kwh
                        ),
                        "batt_discharge_kwh": func.coalesce(
                            stmt.excluded.batt_discharge_kwh, SlotObservation.batt_discharge_kwh
                        ),
                        "soc_start_percent": func.coalesce(
                            stmt.excluded.soc_start_percent, SlotObservation.soc_start_percent
                        ),
                        "soc_end_percent": func.coalesce(
                            stmt.excluded.soc_end_percent, SlotObservation.soc_end_percent
                        ),
                        "import_price_sek_kwh": func.coalesce(
                            stmt.excluded.import_price_sek_kwh, SlotObservation.import_price_sek_kwh
                        ),
                        "export_price_sek_kwh": func.coalesce(
                            stmt.excluded.export_price_sek_kwh, SlotObservation.export_price_sek_kwh
                        ),
                        "quality_flags": quality_flags_update,
                    },
                )
                await session.execute(stmt)
            await session.commit()

    async def store_forecasts(self, forecasts: list[dict[str, Any]], forecast_version: str) -> None:
        """Store forecast data using Async SQLAlchemy."""
        if not forecasts:
            return

        async with self.AsyncSession() as session:
            for forecast in forecasts:
                slot_start_value: Any = forecast.get("slot_start") or forecast.get("start_time")
                if slot_start_value is None:
                    continue
                if isinstance(slot_start_value, datetime | pd.Timestamp):
                    slot_start = slot_start_value.astimezone(self.timezone).isoformat()
                else:
                    slot_start_ts = type_cast("pd.Timestamp", pd.to_datetime(slot_start_value))
                    slot_start = slot_start_ts.astimezone(self.timezone).isoformat()

                stmt = sqlite_insert(SlotForecast).values(
                    slot_start=slot_start,
                    pv_forecast_kwh=float(forecast.get("pv_forecast_kwh", 0.0) or 0.0),
                    openmeteo_pv_forecast_kwh=forecast.get("openmeteo_pv_forecast_kwh"),
                    load_forecast_kwh=float(forecast.get("load_forecast_kwh", 0.0) or 0.0),
                    pv_p10=forecast.get("pv_p10"),
                    pv_p90=forecast.get("pv_p90"),
                    load_p10=forecast.get("load_p10"),
                    load_p90=forecast.get("load_p90"),
                    base_load_forecast_kwh=float(
                        forecast.get("base_load_forecast_kwh", 0.0) or 0.0
                    ),
                    base_load_p10=forecast.get("base_load_p10"),
                    base_load_p90=forecast.get("base_load_p90"),
                    temp_c=forecast.get("temp_c"),
                    forecast_version=forecast_version,
                )
                # UPSERT: Update existing forecasts with new values
                # Note: Correction columns (pv_correction_kwh, load_correction_kwh, correction_source)
                # are no longer written but remain in DB schema for backward compatibility
                stmt = stmt.on_conflict_do_update(
                    index_elements=["slot_start", "forecast_version"],
                    set_={
                        "pv_forecast_kwh": stmt.excluded.pv_forecast_kwh,
                        "openmeteo_pv_forecast_kwh": func.coalesce(
                            stmt.excluded.openmeteo_pv_forecast_kwh,
                            SlotForecast.openmeteo_pv_forecast_kwh,
                        ),
                        "load_forecast_kwh": stmt.excluded.load_forecast_kwh,
                        "pv_p10": stmt.excluded.pv_p10,
                        "pv_p90": stmt.excluded.pv_p90,
                        "load_p10": stmt.excluded.load_p10,
                        "load_p90": stmt.excluded.load_p90,
                        "base_load_forecast_kwh": stmt.excluded.base_load_forecast_kwh,
                        "base_load_p10": stmt.excluded.base_load_p10,
                        "base_load_p90": stmt.excluded.base_load_p90,
                        "temp_c": stmt.excluded.temp_c,
                    },
                )

                await session.execute(stmt)
            await session.commit()

    async def store_plan(self, plan_df: pd.DataFrame) -> None:
        """Store the planned schedule for later comparison using Async SQLAlchemy."""
        if plan_df.empty:
            return

        async with self.AsyncSession() as session:
            records = plan_df.to_dict("records")
            for row in records:
                slot_start_raw = row.get("start_time") or row.get("slot_start")
                if not slot_start_raw:
                    continue

                # slot_start is local ISO with offset (self.timezone), unlike
                # created_at below (naive UTC) — compare only after converting to a common tz.
                slot_start: str
                if isinstance(slot_start_raw, datetime | pd.Timestamp):
                    slot_start = slot_start_raw.astimezone(self.timezone).isoformat()
                else:
                    slot_start = (  # type: ignore[reportUnknownVariableType]
                        pd.to_datetime(slot_start_raw).astimezone(self.timezone).isoformat()  # type: ignore[reportUnknownMemberType]
                    )

                stmt = sqlite_insert(SlotPlan).values(
                    slot_start=slot_start,
                    planned_charge_kwh=float(row.get("kepler_charge_kwh", 0.0) or 0.0),
                    planned_discharge_kwh=float(row.get("kepler_discharge_kwh", 0.0) or 0.0),
                    planned_soc_percent=float(
                        row.get("soc_target_percent", row.get("kepler_soc_percent", 0.0)) or 0.0
                    ),
                    projected_soc_percent=float(
                        row.get(
                            "projected_soc_percent", row.get("kepler_projected_soc_percent", 0.0)
                        )
                        or 0.0
                    ),
                    planned_import_kwh=float(row.get("kepler_import_kwh", 0.0) or 0.0),
                    planned_export_kwh=float(row.get("kepler_export_kwh", 0.0) or 0.0),
                    planned_water_heating_kwh=float(row.get("water_heating_kw", 0.0) or 0.0) * 0.25,
                    planned_cost_sek=float(
                        row.get("planned_cost_sek", row.get("kepler_cost_sek", 0.0)) or 0.0
                    ),
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["slot_start"],
                    set_={
                        "planned_charge_kwh": stmt.excluded.planned_charge_kwh,
                        "planned_discharge_kwh": stmt.excluded.planned_discharge_kwh,
                        "planned_soc_percent": stmt.excluded.planned_soc_percent,
                        "projected_soc_percent": stmt.excluded.projected_soc_percent,
                        "planned_import_kwh": stmt.excluded.planned_import_kwh,
                        "planned_export_kwh": stmt.excluded.planned_export_kwh,
                        "planned_water_heating_kwh": stmt.excluded.planned_water_heating_kwh,
                        "planned_cost_sek": stmt.excluded.planned_cost_sek,
                        # created_at is naive UTC (SQLite CURRENT_TIMESTAMP), unlike
                        # slot_start above (local ISO with offset) — compare only after
                        # converting to a common tz.
                        "created_at": func.current_timestamp(),
                    },
                )
                await session.execute(stmt)
            await session.commit()

    async def store_training_episode(
        self,
        episode_id: str,
        inputs_json: str,
        schedule_json: str,
        context_json: str | None = None,
        config_overrides_json: str | None = None,
    ) -> None:
        """Store a training episode for RL using Async SQLAlchemy."""
        async with self.AsyncSession() as session:
            stmt = (
                sqlite_insert(TrainingEpisode)
                .values(
                    episode_id=episode_id,
                    inputs_json=inputs_json,
                    schedule_json=schedule_json,
                    context_json=context_json,
                    config_overrides_json=config_overrides_json,
                )
                .on_conflict_do_nothing()
            )
            await session.execute(stmt)
            await session.commit()

    async def get_last_observation_time(self) -> datetime | None:
        """Get the timestamp of the last recorded observation using Async SQLAlchemy."""
        async with self.AsyncSession() as session:
            result = await session.scalar(select(func.max(SlotObservation.slot_start)))
            if result:
                dt = datetime.fromisoformat(result)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=self.timezone)
                else:
                    dt = dt.astimezone(self.timezone)
                return dt
            return None

    async def get_low_soc_events(
        self,
        days_back: int = 30,
        threshold_percent: float = 5.0,
        peak_hours: tuple[int, int] = (16, 20),
    ) -> list[dict[str, Any]]:
        """
        Query slot_observations for low-SoC events during peak hours using Async SQLAlchemy.
        """
        cutoff_date = (datetime.now(self.timezone) - timedelta(days=days_back)).date().isoformat()
        start_hour, end_hour = peak_hours

        async with self.AsyncSession() as session:
            stmt = (
                select(
                    func.date(SlotObservation.slot_start),
                    SlotObservation.slot_start,
                    SlotObservation.soc_end_percent,
                )
                .where(
                    func.date(SlotObservation.slot_start) >= cutoff_date,
                    SlotObservation.soc_end_percent.is_not(None),
                    SlotObservation.soc_end_percent < threshold_percent,
                    cast(func.substr(SlotObservation.slot_start, 12, 2), Integer) >= start_hour,
                    cast(func.substr(SlotObservation.slot_start, 12, 2), Integer) < end_hour,
                )
                .order_by(SlotObservation.slot_start.desc())
            )

            result = await session.execute(stmt)
            return [
                {
                    "date": r[0],
                    "slot_start": r[1],
                    "soc_end_percent": r[2],
                }
                for r in result.all()
            ]

    async def get_reflex_state(self, param_path: str) -> dict[str, Any] | None:
        """
        Get the last update state for a parameter using Async SQLAlchemy.
        """
        async with self.AsyncSession() as session:
            state = await session.get(ReflexState, param_path)
            if state:
                return {
                    "last_value": state.last_value,
                    "last_updated": state.last_updated,
                    "change_count": state.change_count,
                }
            return None

    async def update_reflex_state(self, param_path: str, new_value: float) -> None:
        """
        Update the reflex state for a parameter after a change using Async SQLAlchemy.
        """
        now = datetime.now(self.timezone).isoformat()
        async with self.AsyncSession() as session:
            stmt = sqlite_insert(ReflexState).values(
                param_path=param_path, last_value=new_value, last_updated=now, change_count=1
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["param_path"],
                set_={
                    "last_value": stmt.excluded.last_value,
                    "last_updated": stmt.excluded.last_updated,
                    "change_count": ReflexState.change_count + 1,
                },
            )
            await session.execute(stmt)
            await session.commit()

    async def get_system_state(self, key: str) -> str | None:
        """
        Get the specific system state value by key using Async SQLAlchemy.
        """
        async with self.AsyncSession() as session:
            state = await session.get(SystemState, key)
            if state:
                return state.value
            return None

    async def count_paired_openmeteo_pv_days(self, days_back: int = 90) -> int:
        """Count days with both actual PV and a stored Open-Meteo baseline."""
        cutoff_date = (datetime.now(self.timezone) - timedelta(days=days_back)).date().isoformat()

        async with self.AsyncSession() as session:
            stmt = (
                select(func.count(func.distinct(func.date(SlotObservation.slot_start))))
                .join(
                    SlotForecast,
                    (SlotObservation.slot_start == SlotForecast.slot_start)
                    & (SlotForecast.forecast_version == "aurora"),
                )
                .where(
                    func.date(SlotObservation.slot_start) >= cutoff_date,
                    SlotObservation.pv_kwh.is_not(None),
                    SlotObservation.pv_kwh > 0.0,
                    SlotForecast.openmeteo_pv_forecast_kwh.is_not(None),
                )
            )
            result = await session.execute(stmt)
            return int(result.scalar() or 0)

    async def get_pv_observation_days(self, days_back: int = 28) -> set[str]:
        """Return local dates with actual PV production in the recent history window."""
        cutoff_date = (datetime.now(self.timezone) - timedelta(days=days_back)).date().isoformat()

        async with self.AsyncSession() as session:
            stmt = (
                select(func.date(SlotObservation.slot_start))
                .where(
                    func.date(SlotObservation.slot_start) >= cutoff_date,
                    SlotObservation.pv_kwh.is_not(None),
                    SlotObservation.pv_kwh > 0.0,
                )
                .distinct()
            )
            result = await session.execute(stmt)
            return {str(row[0]) for row in result.all() if row[0]}

    async def get_pv_slots_missing_openmeteo_baseline(
        self,
        days_back: int = 28,
        forecast_version: str = "aurora",
    ) -> set[str]:
        """Return actual-PV slots missing a stored Open-Meteo baseline."""
        cutoff_date = (datetime.now(self.timezone) - timedelta(days=days_back)).date().isoformat()

        async with self.AsyncSession() as session:
            stmt = (
                select(SlotObservation.slot_start)
                .outerjoin(
                    SlotForecast,
                    (SlotObservation.slot_start == SlotForecast.slot_start)
                    & (SlotForecast.forecast_version == forecast_version),
                )
                .where(
                    func.date(SlotObservation.slot_start) >= cutoff_date,
                    SlotObservation.pv_kwh.is_not(None),
                    SlotObservation.pv_kwh > 0.0,
                    SlotForecast.openmeteo_pv_forecast_kwh.is_(None),
                )
                .distinct()
            )
            result = await session.execute(stmt)
            return {str(row[0]) for row in result.all() if row[0]}

    async def store_openmeteo_pv_baselines(
        self,
        baselines: list[dict[str, Any]],
        forecast_version: str = "aurora",
    ) -> None:
        """Store Open-Meteo PV baselines without overwriting final forecast values."""
        rows = list(baselines or [])
        if not rows:
            return

        async with self.AsyncSession() as session:
            for row in rows:
                slot_start_value: Any = row.get("slot_start") or row.get("start_time")
                baseline = row.get("openmeteo_pv_forecast_kwh")
                if slot_start_value is None or baseline is None:
                    continue
                if isinstance(slot_start_value, datetime | pd.Timestamp):
                    slot_start = slot_start_value.astimezone(self.timezone).isoformat()
                else:
                    slot_start_ts = type_cast("pd.Timestamp", pd.to_datetime(slot_start_value))
                    slot_start = slot_start_ts.astimezone(self.timezone).isoformat()

                stmt = sqlite_insert(SlotForecast).values(
                    slot_start=slot_start,
                    forecast_version=forecast_version,
                    openmeteo_pv_forecast_kwh=float(baseline),
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["slot_start", "forecast_version"],
                    set_={"openmeteo_pv_forecast_kwh": stmt.excluded.openmeteo_pv_forecast_kwh},
                )
                await session.execute(stmt)
            await session.commit()

    async def get_openmeteo_pv_baselines_range(
        self,
        start: datetime,
        end: datetime,
        forecast_version: str = "aurora",
    ) -> list[dict[str, Any]]:
        """Get stored Open-Meteo PV baselines for a time range."""
        start_iso = start.isoformat()
        end_iso = end.isoformat()

        async with self.AsyncSession() as session:
            stmt = (
                select(SlotForecast.slot_start, SlotForecast.openmeteo_pv_forecast_kwh)
                .where(
                    SlotForecast.slot_start >= start_iso,
                    SlotForecast.slot_start < end_iso,
                    SlotForecast.forecast_version == forecast_version,
                    SlotForecast.openmeteo_pv_forecast_kwh.is_not(None),
                )
                .order_by(SlotForecast.slot_start.asc())
            )
            result = await session.execute(stmt)
            return [row._asdict() for row in result.all()]  # type: ignore

    async def set_system_state(self, key: str, value: str) -> None:
        """
        Set or update a system state value using Async SQLAlchemy.
        """
        now = datetime.now(self.timezone)
        async with self.AsyncSession() as session:
            stmt = sqlite_insert(SystemState).values(key=key, value=value, updated_at=now)
            stmt = stmt.on_conflict_do_update(
                index_elements=["key"],
                set_={"value": stmt.excluded.value, "updated_at": stmt.excluded.updated_at},
            )
            await session.execute(stmt)
            await session.commit()

    async def get_forecast_vs_actual(
        self,
        days_back: int = 14,
        target: str = "pv",
        max_kwh: float | None = None,
    ) -> pd.DataFrame:
        """
        Compare forecast vs actual values for PV or load using Async SQLAlchemy.

        Args:
            days_back: Number of days to look back
            target: "pv" or "load"
            max_kwh: Maximum energy value threshold. Rows with actual values exceeding
                    this threshold will be excluded (spike filtering).
        """
        cutoff_date = (datetime.now(self.timezone) - timedelta(days=days_back)).date().isoformat()

        if target == "pv":
            forecast_col = SlotForecast.pv_forecast_kwh
            actual_col = SlotObservation.pv_kwh
            p10_col = SlotForecast.pv_p10
            p90_col = SlotForecast.pv_p90
        else:
            forecast_col = SlotForecast.load_forecast_kwh
            actual_col = SlotObservation.load_kwh
            p10_col = SlotForecast.load_p10
            p90_col = SlotForecast.load_p90

        async with self.AsyncSession() as session:
            conditions = [
                func.date(SlotObservation.slot_start) >= cutoff_date,
                actual_col.is_not(None),
                forecast_col.is_not(None),
            ]
            if target == "pv":
                # REV F67: Filter out night slots (Bug #3) to avoid diluting bias signal.
                # Only analyze slots where PV production was actually occurring.
                conditions.append(actual_col > 0.01)

            # Spike filtering: exclude rows where actual exceeds threshold
            if max_kwh is not None:
                conditions.append(actual_col <= max_kwh)

            stmt = (
                select(
                    SlotObservation.slot_start,
                    forecast_col.label("forecast"),
                    actual_col.label("actual"),
                    (forecast_col - actual_col).label("error"),
                    p10_col.label("p10"),
                    p90_col.label("p90"),
                )
                .join(
                    SlotForecast,
                    (SlotObservation.slot_start == SlotForecast.slot_start)
                    & (SlotForecast.forecast_version == "aurora"),
                )
                .where(*conditions)
                .order_by(SlotObservation.slot_start.asc())
            )

            result = await session.execute(stmt)
            rows = result.all()
            if not rows:
                return pd.DataFrame()

            # Return as DataFrame
            return pd.DataFrame([row._asdict() for row in rows])  # type: ignore

    async def get_capacity_estimate(self, days_back: int = 30) -> float | None:
        """
        Estimate effective battery capacity from discharge observations using Async SQLAlchemy.
        """
        cutoff_date = (datetime.now(self.timezone) - timedelta(days=days_back)).date().isoformat()

        async with self.AsyncSession() as session:
            stmt = select(
                SlotObservation.soc_start_percent,
                SlotObservation.soc_end_percent,
                SlotObservation.batt_discharge_kwh,
            ).where(
                func.date(SlotObservation.slot_start) >= cutoff_date,
                SlotObservation.soc_start_percent.is_not(None),
                SlotObservation.soc_end_percent.is_not(None),
                SlotObservation.batt_discharge_kwh.is_not(None),
                SlotObservation.batt_discharge_kwh > 0.1,
                SlotObservation.soc_start_percent > SlotObservation.soc_end_percent,
            )

            result = await session.execute(stmt)
            rows = result.all()

            if len(rows) < 10:
                return None

            # Calculate effective capacity from each observation
            estimates: list[float] = []
            for row in rows:
                soc_start: float = row[0]
                soc_end: float = row[1]
                discharge_kwh: float = row[2]
                soc_drop: float = soc_start - soc_end
                if soc_drop > 0.5:  # At least 0.5% drop
                    estimated_cap: float = discharge_kwh / (soc_drop / 100.0)
                    if 10 < estimated_cap < 100:  # Sanity check
                        estimates.append(estimated_cap)

            if len(estimates) < 5:
                return None

            # Use median to be robust to outliers
            estimates.sort()
            median_idx: int = len(estimates) // 2
            return round(estimates[median_idx], 1)

    async def calculate_metrics(
        self, days_back: int = 7, max_kwh: float | None = None
    ) -> dict[str, Any]:
        """Calculate learning metrics using Async SQLAlchemy.

        Args:
            days_back: Number of days to look back
            max_kwh: Maximum energy value threshold. Rows with pv_kwh or load_kwh exceeding
                    this threshold will be excluded from MAE calculations (spike filtering).
        """
        cutoff_date = (datetime.now(self.timezone) - timedelta(days=days_back)).date().isoformat()
        metrics: dict[str, Any] = {}

        async with self.AsyncSession() as session:
            # 1. Forecast Accuracy (PV)
            pv_conditions = [
                func.date(SlotObservation.slot_start) >= cutoff_date,
                SlotObservation.pv_kwh.is_not(None),
                SlotForecast.pv_forecast_kwh.is_not(None),
            ]
            if max_kwh is not None:
                pv_conditions.append(SlotObservation.pv_kwh <= max_kwh)

            stmt_pv = (
                select(func.avg(func.abs(SlotObservation.pv_kwh - SlotForecast.pv_forecast_kwh)))
                .join(
                    SlotForecast,
                    (SlotObservation.slot_start == SlotForecast.slot_start)
                    & (SlotForecast.forecast_version == "aurora"),
                )
                .where(*pv_conditions)
            )

            pv_res = await session.scalar(stmt_pv)
            if pv_res:
                mae = round(pv_res, 4)
                metrics["mae_pv"] = mae
                if mae > 0.5:
                    logger.warning(f"High PV forecast MAE detected: {mae} kWh (Threshold: 0.5)")

            # 2. Load Forecast Accuracy (Prefer Base Load if available)
            load_conditions = [
                func.date(SlotObservation.slot_start) >= cutoff_date,
                SlotObservation.load_kwh.is_not(None),
                SlotForecast.load_forecast_kwh.is_not(None),
            ]
            if max_kwh is not None:
                load_conditions.append(SlotObservation.load_kwh <= max_kwh)

            stmt_load = (
                select(
                    func.avg(
                        func.abs(
                            SlotObservation.load_kwh
                            - func.coalesce(
                                SlotForecast.base_load_forecast_kwh, SlotForecast.load_forecast_kwh
                            )
                        )
                    )
                )
                .join(
                    SlotForecast,
                    (SlotObservation.slot_start == SlotForecast.slot_start)
                    & (SlotForecast.forecast_version == "aurora"),
                )
                .where(*load_conditions)
            )

            load_res = await session.scalar(stmt_load)
            if load_res:
                mae = round(load_res, 4)
                metrics["mae_load"] = mae
                if mae > 0.5:
                    logger.warning(f"High Load forecast MAE detected: {mae} kWh (Threshold: 0.5)")

            # 3. Plan Deviation
            stmt_plan = (
                select(
                    func.avg(
                        func.abs(SlotObservation.batt_charge_kwh - SlotPlan.planned_charge_kwh)
                    ),
                    func.avg(
                        func.abs(
                            SlotObservation.batt_discharge_kwh - SlotPlan.planned_discharge_kwh
                        )
                    ),
                    func.avg(
                        func.abs(SlotObservation.soc_end_percent - SlotPlan.planned_soc_percent)
                    ),
                )
                .join(SlotPlan, SlotObservation.slot_start == SlotPlan.slot_start)
                .where(func.date(SlotObservation.slot_start) >= cutoff_date)
            )

            plan_result = await session.execute(stmt_plan)
            plan_res = plan_result.fetchone()
            if plan_res:
                metrics["mae_plan_charge"] = round(plan_res[0] or 0.0, 4)
                metrics["mae_plan_discharge"] = round(plan_res[1] or 0.0, 4)
                metrics["mae_plan_soc"] = round(plan_res[2] or 0.0, 4)

            # 3. Cost Deviation
            stmt_cost = (
                select(
                    func.sum(
                        SlotObservation.import_kwh * SlotObservation.import_price_sek_kwh
                        - SlotObservation.export_kwh * SlotObservation.export_price_sek_kwh
                    ),
                    func.sum(SlotPlan.planned_cost_sek),
                )
                .join(SlotPlan, SlotObservation.slot_start == SlotPlan.slot_start)
                .where(
                    func.date(SlotObservation.slot_start) >= cutoff_date,
                    SlotObservation.import_price_sek_kwh.is_not(None),
                )
            )

            cost_result = await session.execute(stmt_cost)
            cost_res = cost_result.fetchone()
            if cost_res and cost_res[0] is not None and cost_res[1] is not None:
                metrics["total_realized_cost"] = round(cost_res[0], 2)
                metrics["total_planned_cost"] = round(cost_res[1], 2)
                metrics["cost_deviation"] = round(abs(cost_res[0] - cost_res[1]), 2)

        return metrics

    async def get_performance_series(self, days_back: int = 7) -> dict[str, list[dict[str, Any]]]:
        """Get performance time-series data using Async SQLAlchemy."""
        cutoff_date = (datetime.now(self.timezone) - timedelta(days=days_back)).date().isoformat()

        async with self.AsyncSession() as session:
            # 1. SoC Series
            stmt_soc = (
                select(
                    SlotObservation.slot_start,
                    SlotPlan.planned_soc_percent,
                    SlotObservation.soc_end_percent,
                )
                .outerjoin(SlotPlan, SlotObservation.slot_start == SlotPlan.slot_start)
                .where(func.date(SlotObservation.slot_start) >= cutoff_date)
                .order_by(SlotObservation.slot_start.asc())
            )

            soc_result = await session.execute(stmt_soc)
            soc_results = soc_result.all()
            logger.debug(
                "get_performance_series: found %d SoC records for last %d days",
                len(soc_results),
                days_back,
            )
            soc_series = [{"time": r[0], "planned": r[1], "actual": r[2]} for r in soc_results]

            # 2. Daily Cost Series
            stmt_cost_daily = (
                select(
                    func.date(SlotObservation.slot_start).label("day"),
                    func.sum(SlotPlan.planned_cost_sek),
                    func.sum(
                        func.coalesce(SlotObservation.import_kwh, 0.0)
                        * func.coalesce(SlotObservation.import_price_sek_kwh, 0.0)
                        - func.coalesce(SlotObservation.export_kwh, 0.0)
                        * func.coalesce(SlotObservation.export_price_sek_kwh, 0.0)
                    ),
                )
                .outerjoin(SlotPlan, SlotObservation.slot_start == SlotPlan.slot_start)
                .where(
                    func.date(SlotObservation.slot_start) >= cutoff_date,
                    # Remove strict NOT NULL check on price to allow debugging/partial data
                    # SlotObservation.import_price_sek_kwh.is_not(None),
                )
                .group_by(text("day"))
                .order_by(text("day"))
            )

            cost_result = await session.execute(stmt_cost_daily)
            cost_results = cost_result.all()

            # Debug log
            logger.info("Cost Reality Query: %d daily rows found", len(cost_results))
            for r in cost_results:
                logger.debug("Date: %s, Plan: %s, Real: %s", r[0], r[1], r[2])

            cost_series = [
                {
                    "date": r[0],
                    "planned": round(r[1] or 0.0, 2),
                    "realized": round(r[2] or 0.0, 2),
                }
                for r in cost_results
            ]

        return {"soc_series": soc_series, "cost_series": cost_series}

    async def get_episodes_count(self) -> int:
        """Count training episodes using Async SQLAlchemy."""
        async with self.AsyncSession() as session:
            stmt = select(func.count(TrainingEpisode.episode_id))
            return await session.scalar(stmt) or 0

    async def get_history_range(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Get observation history for a specific range."""
        start_iso = start.isoformat()
        end_iso = end.isoformat()

        async with self.AsyncSession() as session:
            stmt = (
                select(
                    SlotObservation.slot_start,
                    SlotObservation.slot_end,
                    SlotObservation.batt_charge_kwh,
                    SlotObservation.batt_discharge_kwh,
                    SlotObservation.soc_end_percent,
                    SlotObservation.water_kwh,
                    SlotObservation.ev_charging_kwh,
                    SlotObservation.import_kwh,
                    SlotObservation.export_kwh,
                    SlotObservation.import_price_sek_kwh,
                )
                .where(
                    SlotObservation.slot_start >= start_iso, SlotObservation.slot_start < end_iso
                )
                .order_by(SlotObservation.slot_start.asc())
            )

            result = await session.execute(stmt)
            return [row._asdict() for row in result.all()]  # type: ignore

    async def get_forecasts_range(self, start: datetime, version: str) -> list[dict[str, Any]]:
        """Get forecasts for a specific range and version."""
        start_iso = start.isoformat()

        async with self.AsyncSession() as session:
            stmt = select(
                SlotForecast.slot_start,
                SlotForecast.pv_forecast_kwh,
                SlotForecast.openmeteo_pv_forecast_kwh,
                SlotForecast.load_forecast_kwh,
                SlotForecast.pv_p10,
                SlotForecast.pv_p90,
                SlotForecast.load_p10,
                SlotForecast.load_p90,
                SlotForecast.base_load_forecast_kwh,
                SlotForecast.base_load_p10,
                SlotForecast.base_load_p90,
                SlotForecast.temp_c,
                SlotForecast.forecast_version,
                SlotForecast.pv_correction_kwh,
                SlotForecast.load_correction_kwh,
                SlotForecast.correction_source,
            ).where(SlotForecast.slot_start >= start_iso, SlotForecast.forecast_version == version)
            result = await session.execute(stmt)
            return [row._asdict() for row in result.all()]  # type: ignore

    async def get_plans_range(self, start: datetime) -> list[dict[str, Any]]:
        """Get planned slots from a specific start time."""
        start_iso = start.isoformat()

        async with self.AsyncSession() as session:
            stmt = (
                select(
                    SlotPlan.slot_start,
                    SlotPlan.planned_charge_kwh,
                    SlotPlan.planned_discharge_kwh,
                    SlotPlan.planned_soc_percent,
                    SlotPlan.projected_soc_percent,
                    SlotPlan.planned_export_kwh,
                    SlotPlan.planned_water_heating_kwh,
                )
                .where(SlotPlan.slot_start >= start_iso)
                .order_by(SlotPlan.slot_start.asc())
            )

            result = await session.execute(stmt)
            return [row._asdict() for row in result.all()]  # type: ignore

    async def get_observations_range(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Get actual observations (PV, Load, Water) from slot_observations for a date range."""
        start_iso = start.isoformat()
        end_iso = end.isoformat()

        async with self.AsyncSession() as session:
            stmt = (
                select(
                    SlotObservation.slot_start,
                    SlotObservation.pv_kwh,
                    SlotObservation.load_kwh,
                    SlotObservation.water_kwh,
                )
                .where(
                    SlotObservation.slot_start >= start_iso,
                    SlotObservation.slot_start < end_iso,
                )
                .order_by(SlotObservation.slot_start.asc())
            )

            result = await session.execute(stmt)
            return [row._asdict() for row in result.all()]  # type: ignore

    async def get_executions_range(self, start: datetime) -> list[dict[str, Any]]:
        """Get execution history from execution_log table, grouped by slot_start."""
        start_iso = start.isoformat()

        async with self.AsyncSession() as session:
            stmt = (
                select(ExecutionLog)
                .where(ExecutionLog.slot_start >= start_iso)
                .order_by(ExecutionLog.executed_at.asc())
            )

            result = await session.execute(stmt)
            rows = result.scalars().all()

            # Group by slot_start
            slots: dict[str, list[ExecutionLog]] = {}
            for r in rows:
                ss = r.slot_start
                if ss not in slots:
                    slots[ss] = []
                slots[ss].append(r)

            results: list[dict[str, Any]] = []
            for ss, entries in slots.items():
                if not entries:
                    continue

                # Last entry for SoC (representing end of slot state as it progresses)
                last_entry = entries[-1]

                # Average power for the slot (ExecutionLog records every minute)
                avg_charge_kw = sum((e.planned_charge_kw or 0.0) for e in entries) / len(entries)
                avg_discharge_kw = sum((e.planned_discharge_kw or 0.0) for e in entries) / len(
                    entries
                )
                avg_water_kw = sum((e.planned_water_kw or 0.0) for e in entries) / len(entries)
                avg_export_kw = sum((e.planned_export_kw or 0.0) for e in entries) / len(entries)

                # Estimate slot end (15 mins)
                try:
                    s_start_dt = datetime.fromisoformat(ss)
                    s_end_dt = s_start_dt + timedelta(minutes=15)
                    slot_end = s_end_dt.isoformat()
                except Exception:
                    slot_end = ss

                results.append(
                    {
                        "slot_start": ss,
                        "slot_end": slot_end,
                        # Map to names expected by schedule API (mocking SlotObservation fields)
                        # schedule.py expects kWh fields (and divides by duration), so we provide kWh.
                        "batt_charge_kwh": avg_charge_kw * 0.25,
                        "batt_discharge_kwh": avg_discharge_kw * 0.25,
                        "water_kwh": avg_water_kw * 0.25,
                        "export_kwh": avg_export_kw * 0.25,
                        "import_price_sek_kwh": None,
                        "soc_end_percent": float(last_entry.planned_soc_projected or 0.0),
                    }
                )

            return results

    async def get_db_stats(self) -> dict[str, Any]:
        """Get database statistics (size, row counts) using Async SQLAlchemy."""
        stats = {
            "size_mb": 0.0,
            "slot_plans_count": 0,
            "slot_observations_count": 0,
            "health": "unknown",
        }

        # 1. Get file size
        try:
            db_path = Path(self.db_path)
            if db_path.exists():
                stats["size_mb"] = round(db_path.stat().st_size / (1024 * 1024), 2)
        except Exception:
            pass

        # 2. Get row counts
        async with self.AsyncSession() as session:
            try:
                # Count plans
                count_plans = await session.scalar(select(func.count(SlotPlan.slot_start)))
                stats["slot_plans_count"] = count_plans or 0

                # Count observations
                count_obs = await session.scalar(select(func.count(SlotObservation.slot_start)))
                stats["slot_observations_count"] = count_obs or 0

                stats["health"] = "good"
            except Exception as e:
                logger.error(f"Error getting DB stats: {e}")
                stats["health"] = "error"

        return stats

    async def get_learning_stats(self) -> dict[str, Any]:
        """Get learning statistics using Async SQLAlchemy."""
        async with self.AsyncSession() as session:
            # Count runs
            count_stmt = select(func.count(LearningRun.id))
            total_runs = await session.scalar(count_stmt) or 0

            # Last run
            last_stmt = select(LearningRun).order_by(desc(LearningRun.started_at)).limit(1)
            result = await session.execute(last_stmt)
            last_run = result.scalar_one_or_none()

            status = "infant"
            if total_runs > 10:
                status = "statistician"
            if total_runs > 100:
                status = "graduate"

            return {
                "total_runs": total_runs,
                "status": status,
                "last_run": last_run.started_at.isoformat()
                if last_run and last_run.started_at
                else None,
            }

    async def log_learning_run(
        self,
        status: str,
        result_metrics: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        started_at: datetime | None = None,
        training_type: str | None = None,
        models_trained: list[str] | None = None,
        duration_seconds: int | None = None,
        partial_failure: bool = False,
        error_message: str | None = None,
    ) -> None:
        """Log a learning run execution (ARC11)."""
        if started_at is None:
            started_at = datetime.now(UTC)

        import json

        async with self.AsyncSession() as session:
            run = LearningRun(
                started_at=started_at,
                status=status,
                result_metrics_json=json.dumps(result_metrics) if result_metrics else None,
                params_json=json.dumps(params) if params else None,
                training_type=training_type,
                models_trained=json.dumps(models_trained) if models_trained else None,
                training_duration_seconds=duration_seconds,
                partial_failure=partial_failure,
                error_message=error_message,
                completed_at=datetime.now(UTC)
                if status in ["success", "error", "failed"]
                else None,
            )
            session.add(run)
            await session.commit()

    async def cleanup_learning_runs(self, days_back: int = 30) -> int:
        """Delete learning run records older than days_back (ARC11)."""
        cutoff = datetime.now(UTC) - timedelta(days=days_back)
        async with self.AsyncSession() as session:
            from sqlalchemy import delete

            stmt = delete(LearningRun).where(LearningRun.started_at < cutoff)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount  # type: ignore

    async def get_latest_metrics(self) -> dict[str, Any] | None:
        """Get the latest daily metrics for overlays using Async SQLAlchemy."""
        async with self.AsyncSession() as session:
            stmt = select(LearningDailyMetric).order_by(LearningDailyMetric.date.desc()).limit(1)
            result = await session.execute(stmt)
            metric = result.scalar_one_or_none()
            if not metric:
                return None

            return {
                "date": metric.date,
                "pv_adjustment_by_hour_kwh": metric.pv_adjustment_by_hour_kwh,
                "load_adjustment_by_hour_kwh": metric.load_adjustment_by_hour_kwh,
                "s_index_base_factor": metric.s_index_base_factor,
            }
