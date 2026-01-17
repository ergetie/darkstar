import logging
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import pytz
from sqlalchemy import create_engine, func, select, text, cast, Integer
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import sessionmaker

from backend.learning.models import (
    ReflexState,
    SlotForecast,
    SlotObservation,
    SlotPlan,
    TrainingEpisode,
)

logger = logging.getLogger("darkstar.learning.store")


class LearningStore:
    """
    Handles all database interactions for the Learning Engine using SQLAlchemy.
    """

    def __init__(self, db_path: str, timezone: pytz.timezone):
        self.db_path = db_path
        self.timezone = timezone

        # Initialize SQLAlchemy
        # We use check_same_thread=False for SQLite shared access in FastAPI
        connect_args = {"check_same_thread": False, "timeout": 30.0}
        self.engine = create_engine(f"sqlite:///{db_path}", connect_args=connect_args)
        self.Session = sessionmaker(bind=self.engine)

    # _init_schema was removed as Alembic handles migrations.

    def store_slot_prices(self, price_rows: Iterable[dict[str, Any]]) -> None:
        """Store slot price data (import/export SEK per kWh) using SQLAlchemy."""
        rows = list(price_rows or [])
        if not rows:
            return

        with self.Session() as session:
            for row in rows:
                slot_start = row.get("slot_start") or row.get("start_time")
                slot_end = row.get("slot_end") or row.get("end_time")
                if slot_start is None:
                    continue

                if isinstance(slot_start, (datetime, pd.Timestamp)):
                    slot_start = slot_start.astimezone(self.timezone).isoformat()
                else:
                    slot_start = pd.to_datetime(slot_start).astimezone(self.timezone).isoformat()

                if slot_end is not None:
                    if isinstance(slot_end, (datetime, pd.Timestamp)):
                        slot_end = slot_end.astimezone(self.timezone).isoformat()
                    else:
                        slot_end = pd.to_datetime(slot_end).astimezone(self.timezone).isoformat()

                import_price = row.get("import_price_sek_kwh")
                export_price = row.get("export_price_sek_kwh")

                stmt = sqlite_insert(SlotObservation).values(
                    slot_start=slot_start,
                    slot_end=slot_end,
                    import_price_sek_kwh=import_price,
                    export_price_sek_kwh=export_price
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=['slot_start'],
                    set_={
                        'slot_end': func.coalesce(stmt.excluded.slot_end, SlotObservation.slot_end),
                        'import_price_sek_kwh': func.coalesce(
                            stmt.excluded.import_price_sek_kwh,
                            SlotObservation.import_price_sek_kwh
                        ),
                        'export_price_sek_kwh': func.coalesce(
                            stmt.excluded.export_price_sek_kwh,
                            SlotObservation.export_price_sek_kwh
                        )
                    }
                )
                session.execute(stmt)
            session.commit()

    def store_slot_observations(self, observations_df: pd.DataFrame) -> None:
        """Store slot observations in database using SQLAlchemy."""
        if observations_df.empty:
            return

        with self.Session() as session:
            records = observations_df.to_dict("records")

            for record in records:
                slot_start = record["slot_start"]
                slot_end = record.get("slot_end")

                if isinstance(slot_start, (datetime, pd.Timestamp)):
                    slot_start = slot_start.astimezone(self.timezone).isoformat()
                else:
                    slot_start = pd.to_datetime(slot_start).astimezone(self.timezone).isoformat()

                if slot_end is not None:
                    if isinstance(slot_end, (datetime, pd.Timestamp)):
                        slot_end = slot_end.astimezone(self.timezone).isoformat()
                    else:
                        slot_end = pd.to_datetime(slot_end).astimezone(self.timezone).isoformat()

                stmt = sqlite_insert(SlotObservation).values(
                    slot_start=slot_start,
                    slot_end=slot_end,
                    import_kwh=float(record.get("import_kwh", 0.0) or 0.0),
                    export_kwh=float(record.get("export_kwh", 0.0) or 0.0),
                    pv_kwh=float(record.get("pv_kwh", 0.0) or 0.0),
                    load_kwh=float(record.get("load_kwh", 0.0) or 0.0),
                    water_kwh=float(record.get("water_kwh", 0.0) or 0.0),
                    batt_charge_kwh=record.get("batt_charge_kwh"),
                    batt_discharge_kwh=record.get("batt_discharge_kwh"),
                    soc_start_percent=record.get("soc_start_percent"),
                    soc_end_percent=record.get("soc_end_percent"),
                    import_price_sek_kwh=record.get("import_price_sek_kwh"),
                    export_price_sek_kwh=record.get("export_price_sek_kwh"),
                    quality_flags=record.get("quality_flags", "{}")
                )

                stmt = stmt.on_conflict_do_update(
                    index_elements=['slot_start'],
                    set_={
                        'slot_end': func.coalesce(stmt.excluded.slot_end, SlotObservation.slot_end),
                        'import_kwh': stmt.excluded.import_kwh,
                        'export_kwh': stmt.excluded.export_kwh,
                        'pv_kwh': stmt.excluded.pv_kwh,
                        'load_kwh': stmt.excluded.load_kwh,
                        'water_kwh': stmt.excluded.water_kwh,
                        'batt_charge_kwh': func.coalesce(stmt.excluded.batt_charge_kwh, SlotObservation.batt_charge_kwh),
                        'batt_discharge_kwh': func.coalesce(stmt.excluded.batt_discharge_kwh, SlotObservation.batt_discharge_kwh),
                        'soc_start_percent': func.coalesce(stmt.excluded.soc_start_percent, SlotObservation.soc_start_percent),
                        'soc_end_percent': func.coalesce(stmt.excluded.soc_end_percent, SlotObservation.soc_end_percent),
                        'import_price_sek_kwh': func.coalesce(stmt.excluded.import_price_sek_kwh, SlotObservation.import_price_sek_kwh),
                        'export_price_sek_kwh': func.coalesce(stmt.excluded.export_price_sek_kwh, SlotObservation.export_price_sek_kwh),
                        'quality_flags': stmt.excluded.quality_flags
                    }
                )
                session.execute(stmt)
            session.commit()

    def store_forecasts(self, forecasts: list[dict], forecast_version: str) -> None:
        """Store forecast data using SQLAlchemy."""
        if not forecasts:
            return

        with self.Session() as session:
            for forecast in forecasts:
                slot_start = forecast.get("slot_start")
                if slot_start is None:
                    continue

                stmt = sqlite_insert(SlotForecast).values(
                    slot_start=slot_start,
                    pv_forecast_kwh=float(forecast.get("pv_forecast_kwh", 0.0) or 0.0),
                    load_forecast_kwh=float(forecast.get("load_forecast_kwh", 0.0) or 0.0),
                    pv_p10=forecast.get("pv_p10"),
                    pv_p90=forecast.get("pv_p90"),
                    load_p10=forecast.get("load_p10"),
                    load_p90=forecast.get("load_p90"),
                    temp_c=forecast.get("temp_c"),
                    forecast_version=forecast_version
                )
                # Preserve corrections on conflict
                stmt = stmt.on_conflict_do_update(
                    index_elements=['slot_start', 'forecast_version'],
                    set_={
                        'pv_forecast_kwh': stmt.excluded.pv_forecast_kwh,
                        'load_forecast_kwh': stmt.excluded.load_forecast_kwh,
                        'pv_p10': stmt.excluded.pv_p10,
                        'pv_p90': stmt.excluded.pv_p90,
                        'load_p10': stmt.excluded.load_p10,
                        'load_p90': stmt.excluded.load_p90,
                        'temp_c': stmt.excluded.temp_c
                    }
                )
                session.execute(stmt)
            session.commit()

    def store_plan(self, plan_df: pd.DataFrame) -> None:
        """
        Store the planned schedule for later comparison with actuals using SQLAlchemy.
        """
        if plan_df.empty:
            return

        with self.Session() as session:
            records = plan_df.to_dict("records")
            for row in records:
                slot_start = row.get("start_time") or row.get("slot_start")
                if not slot_start:
                    continue

                if isinstance(slot_start, (datetime, pd.Timestamp)):
                    slot_start = slot_start.astimezone(self.timezone).isoformat()
                else:
                    slot_start = pd.to_datetime(slot_start).astimezone(self.timezone).isoformat()

                stmt = sqlite_insert(SlotPlan).values(
                    slot_start=slot_start,
                    planned_charge_kwh=float(row.get("kepler_charge_kwh", 0.0) or 0.0),
                    planned_discharge_kwh=float(row.get("kepler_discharge_kwh", 0.0) or 0.0),
                    planned_soc_percent=float(
                        row.get("soc_target_percent", row.get("kepler_soc_percent", 0.0)) or 0.0
                    ),
                    planned_import_kwh=float(row.get("kepler_import_kwh", 0.0) or 0.0),
                    planned_export_kwh=float(row.get("kepler_export_kwh", 0.0) or 0.0),
                    planned_water_heating_kwh=float(row.get("water_heating_kw", 0.0) or 0.0) * 0.25,
                    planned_cost_sek=float(row.get("planned_cost_sek", row.get("kepler_cost_sek", 0.0)) or 0.0)
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=['slot_start'],
                    set_={
                        'planned_charge_kwh': stmt.excluded.planned_charge_kwh,
                        'planned_discharge_kwh': stmt.excluded.planned_discharge_kwh,
                        'planned_soc_percent': stmt.excluded.planned_soc_percent,
                        'planned_import_kwh': stmt.excluded.planned_import_kwh,
                        'planned_export_kwh': stmt.excluded.planned_export_kwh,
                        'planned_water_heating_kwh': stmt.excluded.planned_water_heating_kwh,
                        'planned_cost_sek': stmt.excluded.planned_cost_sek,
                        'created_at': func.current_timestamp()
                    }
                )
                session.execute(stmt)
            session.commit()

    def store_training_episode(
        self,
        episode_id: str,
        inputs_json: str,
        schedule_json: str,
        context_json: str | None = None,
        config_overrides_json: str | None = None,
    ) -> None:
        """Store a training episode for RL using SQLAlchemy."""
        with self.Session() as session:
            stmt = sqlite_insert(TrainingEpisode).values(
                episode_id=episode_id,
                inputs_json=inputs_json,
                schedule_json=schedule_json,
                context_json=context_json,
                config_overrides_json=config_overrides_json
            ).on_conflict_do_nothing()
            session.execute(stmt)
            session.commit()

    def get_last_observation_time(self) -> datetime | None:
        """Get the timestamp of the last recorded observation using SQLAlchemy."""
        with self.Session() as session:
            result = session.query(func.max(SlotObservation.slot_start)).scalar()
            if result:
                # Parse ISO string
                dt = datetime.fromisoformat(result)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=self.timezone)
                else:
                    dt = dt.astimezone(self.timezone)
                return dt
            return None

    def get_low_soc_events(
        self,
        days_back: int = 30,
        threshold_percent: float = 5.0,
        peak_hours: tuple[int, int] = (16, 20),
    ) -> list[dict[str, Any]]:
        """
        Query slot_observations for low-SoC events during peak hours using SQLAlchemy.
        """
        cutoff_date = (
            (datetime.now(self.timezone) - timedelta(days=days_back)).date().isoformat()
        )
        start_hour, end_hour = peak_hours

        with self.Session() as session:
            stmt = select(
                func.date(SlotObservation.slot_start),
                SlotObservation.slot_start,
                SlotObservation.soc_end_percent
            ).where(
                func.date(SlotObservation.slot_start) >= cutoff_date,
                SlotObservation.soc_end_percent.is_not(None),
                SlotObservation.soc_end_percent < threshold_percent,
                cast(func.strftime('%H', SlotObservation.slot_start), Integer) >= start_hour,
                cast(func.strftime('%H', SlotObservation.slot_start), Integer) < end_hour
            ).order_by(SlotObservation.slot_start.desc())

            results = session.execute(stmt).all()
            return [
                {
                    "date": r[0],
                    "slot_start": r[1],
                    "soc_end_percent": r[2],
                }
                for r in results
            ]

    def get_reflex_state(self, param_path: str) -> dict[str, Any] | None:
        """
        Get the last update state for a parameter using SQLAlchemy.
        """
        with self.Session() as session:
            state = session.get(ReflexState, param_path)
            if state:
                return {
                    "last_value": state.last_value,
                    "last_updated": state.last_updated,
                    "change_count": state.change_count,
                }
            return None

    def update_reflex_state(self, param_path: str, new_value: float) -> None:
        """
        Update the reflex state for a parameter after a change using SQLAlchemy.
        """
        now = datetime.now(self.timezone).isoformat()
        with self.Session() as session:
            stmt = sqlite_insert(ReflexState).values(
                param_path=param_path,
                last_value=new_value,
                last_updated=now,
                change_count=1
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=['param_path'],
                set_={
                    'last_value': stmt.excluded.last_value,
                    'last_updated': stmt.excluded.last_updated,
                    'change_count': ReflexState.change_count + 1
                }
            )
            session.execute(stmt)
            session.commit()

    def get_forecast_vs_actual(
        self,
        days_back: int = 14,
        target: str = "pv",
    ) -> pd.DataFrame:
        """
        Compare forecast vs actual values for PV or load using SQLAlchemy.
        """
        cutoff_date = (
            (datetime.now(self.timezone) - timedelta(days=days_back)).date().isoformat()
        )

        if target == "pv":
            forecast_col = "f.pv_forecast_kwh"
            actual_col = "o.pv_kwh"
            p10_col = "f.pv_p10"
            p90_col = "f.pv_p90"
        else:
            forecast_col = "f.load_forecast_kwh"
            actual_col = "o.load_kwh"
            p10_col = "f.load_p10"
            p90_col = "f.load_p90"

        query = f"""
            SELECT
                o.slot_start,
                {forecast_col} as forecast,
                {actual_col} as actual,
                ({forecast_col} - {actual_col}) as error,
                {p10_col} as p10,
                {p90_col} as p90
            FROM slot_observations o
            JOIN slot_forecasts f ON o.slot_start = f.slot_start
            WHERE DATE(o.slot_start) >= :cutoff
              AND {actual_col} IS NOT NULL
              AND {forecast_col} IS NOT NULL
            ORDER BY o.slot_start ASC
        """

        # Using engine.connect() for pd.read_sql
        with self.engine.connect() as conn:
            df = pd.read_sql(text(query), conn, params={"cutoff": cutoff_date})
            return df

    def get_arbitrage_stats(self, days_back: int = 30) -> dict[str, Any]:
        """
        Calculate arbitrage statistics for ROI analysis using SQLAlchemy.
        """
        cutoff_date = (
            (datetime.now(self.timezone) - timedelta(days=days_back)).date().isoformat()
        )

        with self.Session() as session:
            stmt = select(
                func.sum(SlotObservation.export_kwh * SlotObservation.export_price_sek_kwh),
                func.sum(SlotObservation.import_kwh * SlotObservation.import_price_sek_kwh),
                func.sum(SlotObservation.batt_charge_kwh),
                func.sum(SlotObservation.batt_discharge_kwh)
            ).where(
                func.date(SlotObservation.slot_start) >= cutoff_date,
                SlotObservation.export_price_sek_kwh.is_not(None),
                SlotObservation.import_price_sek_kwh.is_not(None)
            )

            row = session.execute(stmt).fetchone()

            export_revenue = row[0] or 0.0
            import_cost = row[1] or 0.0
            total_charge = row[2] or 0.0
            total_discharge = row[3] or 0.0

            return {
                "total_export_revenue": round(export_revenue, 2),
                "total_import_cost": round(import_cost, 2),
                "total_charge_kwh": round(total_charge, 2),
                "total_discharge_kwh": round(total_discharge, 2),
                "net_profit": round(export_revenue - import_cost, 2),
            }

    def get_capacity_estimate(self, days_back: int = 30) -> float | None:
        """
        Estimate effective battery capacity from discharge observations using SQLAlchemy.
        """
        cutoff_date = (
            (datetime.now(self.timezone) - timedelta(days=days_back)).date().isoformat()
        )

        with self.Session() as session:
            stmt = select(
                SlotObservation.soc_start_percent,
                SlotObservation.soc_end_percent,
                SlotObservation.batt_discharge_kwh
            ).where(
                func.date(SlotObservation.slot_start) >= cutoff_date,
                SlotObservation.soc_start_percent.is_not(None),
                SlotObservation.soc_end_percent.is_not(None),
                SlotObservation.batt_discharge_kwh.is_not(None),
                SlotObservation.batt_discharge_kwh > 0.1,
                SlotObservation.soc_start_percent > SlotObservation.soc_end_percent
            )

            rows = session.execute(stmt).all()

            if len(rows) < 10:
                return None

            # Calculate effective capacity from each observation
            estimates = []
            for soc_start, soc_end, discharge_kwh in rows:
                soc_drop = soc_start - soc_end
                if soc_drop > 0.5:  # At least 0.5% drop
                    estimated_cap = discharge_kwh / (soc_drop / 100.0)
                    if 10 < estimated_cap < 100:  # Sanity check
                        estimates.append(estimated_cap)

            if len(estimates) < 5:
                return None

            # Use median to be robust to outliers
            estimates.sort()
            median_idx = len(estimates) // 2
            return round(estimates[median_idx], 1)

    def calculate_metrics(self, days_back: int = 7) -> dict[str, Any]:
        """Calculate learning metrics using SQLAlchemy."""
        cutoff_date = (datetime.now(self.timezone) - timedelta(days=days_back)).date().isoformat()
        metrics = {}

        with self.Session() as session:
            # 1. Forecast Accuracy
            stmt_pv = select(func.avg(func.abs(SlotObservation.pv_kwh - SlotForecast.pv_forecast_kwh))).join(
                SlotForecast, SlotObservation.slot_start == SlotForecast.slot_start
            ).where(func.date(SlotObservation.slot_start) >= cutoff_date)

            pv_res = session.execute(stmt_pv).scalar()
            if pv_res:
                metrics["mae_pv"] = round(pv_res, 4)

            # 2. Plan Deviation
            stmt_plan = select(
                func.avg(func.abs(SlotObservation.batt_charge_kwh - SlotPlan.planned_charge_kwh)),
                func.avg(func.abs(SlotObservation.batt_discharge_kwh - SlotPlan.planned_discharge_kwh)),
                func.avg(func.abs(SlotObservation.soc_end_percent - SlotPlan.planned_soc_percent))
            ).join(
                SlotPlan, SlotObservation.slot_start == SlotPlan.slot_start
            ).where(func.date(SlotObservation.slot_start) >= cutoff_date)

            plan_res = session.execute(stmt_plan).fetchone()
            if plan_res:
                metrics["mae_plan_charge"] = round(plan_res[0] or 0.0, 4)
                metrics["mae_plan_discharge"] = round(plan_res[1] or 0.0, 4)
                metrics["mae_plan_soc"] = round(plan_res[2] or 0.0, 4)

            # 3. Cost Deviation
            stmt_cost = select(
                func.sum(SlotObservation.import_kwh * SlotObservation.import_price_sek_kwh -
                         SlotObservation.export_kwh * SlotObservation.export_price_sek_kwh),
                func.sum(SlotPlan.planned_cost_sek)
            ).join(
                SlotPlan, SlotObservation.slot_start == SlotPlan.slot_start
            ).where(
                func.date(SlotObservation.slot_start) >= cutoff_date,
                SlotObservation.import_price_sek_kwh.is_not(None)
            )

            cost_res = session.execute(stmt_cost).fetchone()
            if cost_res and cost_res[0] is not None and cost_res[1] is not None:
                metrics["total_realized_cost"] = round(cost_res[0], 2)
                metrics["total_planned_cost"] = round(cost_res[1], 2)
                metrics["cost_deviation"] = round(abs(cost_res[0] - cost_res[1]), 2)

        return metrics

    def get_performance_series(self, days_back: int = 7) -> dict[str, list[dict]]:
        """Get performance time-series data using SQLAlchemy."""
        cutoff_date = (datetime.now(self.timezone) - timedelta(days=days_back)).date().isoformat()

        with self.Session() as session:
            # 1. SoC Series
            stmt_soc = select(
                SlotObservation.slot_start,
                SlotPlan.planned_soc_percent,
                SlotObservation.soc_end_percent
            ).outerjoin(
                SlotPlan, SlotObservation.slot_start == SlotPlan.slot_start
            ).where(func.date(SlotObservation.slot_start) >= cutoff_date).order_by(SlotObservation.slot_start.asc())

            soc_results = session.execute(stmt_soc).all()
            soc_series = [{"time": r[0], "planned": r[1], "actual": r[2]} for r in soc_results]

            # 2. Daily Cost Series
            stmt_cost_daily = select(
                func.date(SlotObservation.slot_start).label("day"),
                func.sum(SlotPlan.planned_cost_sek),
                func.sum(SlotObservation.import_kwh * SlotObservation.import_price_sek_kwh -
                         SlotObservation.export_kwh * SlotObservation.export_price_sek_kwh)
            ).outerjoin(
                SlotPlan, SlotObservation.slot_start == SlotPlan.slot_start
            ).where(
                func.date(SlotObservation.slot_start) >= cutoff_date,
                SlotObservation.import_price_sek_kwh.is_not(None)
            ).group_by("day").order_by("day")

            cost_results = session.execute(stmt_cost_daily).all()
            cost_series = [
                {
                    "date": r[0],
                    "planned": round(r[1] or 0.0, 2),
                    "realized": round(r[2] or 0.0, 2),
                }
                for r in cost_results
            ]

        return {"soc_series": soc_series, "cost_series": cost_series}

    def get_episodes_count(self) -> int:
        """Count training episodes using SQLAlchemy."""
        with self.Session() as session:
            return session.query(func.count(TrainingEpisode.episode_id)).scalar() or 0
