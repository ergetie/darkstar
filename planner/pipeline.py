"""
Planner Pipeline

Main orchestrator for the modular planner pipeline.
Coordinates Input → Strategy → Solver → Output flow.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
import pytz

if TYPE_CHECKING:
    from datetime import datetime

from backend.learning.store import LearningStore
from planner.inputs.data_prep import apply_safety_margins, prepare_df
from planner.inputs.learning import load_learning_overlays
from planner.inputs.weather import fetch_temperature_forecast
from planner.output.schedule import save_schedule_to_json
from planner.output.soc_target import apply_soc_target_percent
from planner.solver.adapter import (
    config_to_kepler_config,
    kepler_result_to_dataframe,
    planner_to_kepler_input,
)
from planner.solver.kepler import KeplerSolver
from planner.strategy.manual_plan import apply_manual_plan
from planner.strategy.s_index import (
    calculate_dynamic_s_index,
    calculate_dynamic_target_soc,
    calculate_future_risk_factor,
    calculate_probabilistic_s_index,
)
from planner.vacation_state import load_last_anti_legionella, save_last_anti_legionella

logger = logging.getLogger("darkstar.planner")


class PlannerPipeline:
    """
    Orchestrator for the modular planner pipeline.

    Modes:
        - "full": Aurora overlays + Strategy + Kepler (production)
        - "baseline": Kepler only, no Aurora overlays (for A/B comparison)
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize the pipeline with configuration.

        Args:
            config: Configuration dictionary (from config.yaml)
        """
        self.config = config
        self._validate_config()

    def _validate_config(self) -> None:
        """Validate critical configuration values."""
        required_sections = ["battery", "battery_economics"]
        for section in required_sections:
            if section not in self.config:
                raise ValueError(f"Missing required config section: {section}")

        # Validate system profile toggle consistency (REV LCL01)
        system_cfg = self.config.get("system", {})
        water_cfg = self.config.get("water_heating", {})
        battery_cfg = self.config.get("battery", {})

        # Battery: ERROR if enabled but no capacity (breaks MILP solver)
        if system_cfg.get("has_battery", True):
            capacity = float(battery_cfg.get("capacity_kwh", 0.0))
            if capacity <= 0:
                raise ValueError(
                    "Config error: system.has_battery is true but "
                    "battery.capacity_kwh is not set (or is 0). "
                    "Set battery.capacity_kwh or set system.has_battery to false."
                )

        # Water heater: WARNING only (doesn't break system, just disables feature)
        if system_cfg.get("has_water_heater", True):
            power_kw = float(water_cfg.get("power_kw", 0.0))
            if power_kw <= 0:
                logger.warning(
                    "Config warning: has_water_heater=true but water_heating.power_kw=0. "
                    "Water heating optimization is disabled."
                )

        # Solar: WARNING only (doesn't break system, just zeros PV forecasts)
        if system_cfg.get("has_solar", True):
            solar_cfg = system_cfg.get("solar_array", {})
            kwp = float(solar_cfg.get("kwp", 0.0))
            if kwp <= 0:
                logger.warning(
                    "Config warning: has_solar=true but solar_array.kwp=0. "
                    "PV forecasts will be zero."
                )


    def _apply_overrides(self, config: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        """Apply configuration overrides recursively."""
        new_config = copy.deepcopy(config)

        def update_recursive(d, u):
            for k, v in u.items():
                if isinstance(v, dict):
                    d[k] = update_recursive(d.get(k, {}), v)
                else:
                    d[k] = v
            return d

        return update_recursive(new_config, overrides)

    def generate_schedule(
        self,
        input_data: dict[str, Any],
        overrides: dict[str, Any] | None = None,
        mode: str = "full",
        save_to_file: bool = True,
        record_training_episode: bool = False,
        now_override: datetime | None = None,
    ) -> pd.DataFrame:
        """
        Generate an optimal battery schedule.

        Args:
            input_data: Dictionary with price_data, forecast_data, initial_state
            overrides: Optional configuration overrides
            mode: "full" (Aurora + Kepler) or "baseline" (Kepler only)
            save_to_file: Whether to save schedule.json
            record_training_episode: Whether to log training episode (RL)
            now_override: Override current time for simulation/replay

        Returns:
            DataFrame with the complete schedule
        """
        logger.info("PlannerPipeline.generate_schedule(mode=%s)", mode)

        # 1. Configuration & Overrides
        active_config = self.config
        if overrides:
            active_config = self._apply_overrides(self.config, overrides)

        # System Profile Toggles (Rev O1)
        system_cfg = active_config.get("system", {})
        has_solar = system_cfg.get("has_solar", True)
        has_battery = system_cfg.get("has_battery", True)
        has_water_heater = system_cfg.get("has_water_heater", True)
        water_cfg = active_config.get("water_heating", {})

        logger.info(
            "System profile: solar=%s, battery=%s, water=%s",
            has_solar,
            has_battery,
            has_water_heater,
        )

        # 2. Load Inputs
        # Load learning overlays (PV/Load bias, S-Index base)
        learning_overlays = {}
        if mode == "full":
            learning_overlays = load_learning_overlays(active_config.get("learning", {}))

        # Prepare DataFrame (merge prices + forecasts)
        timezone_name = active_config.get("timezone", "Europe/Stockholm")
        df = prepare_df(input_data, timezone_name)

        # Rev O1: Zero out PV if no solar panels
        if not has_solar:
            logger.info("No solar panels - zeroing PV forecasts")
            df["pv_forecast_kwh"] = 0.0
            if "adjusted_pv_kwh" in df.columns:
                df["adjusted_pv_kwh"] = 0.0

        # Determine 'now' slot
        tz = pytz.timezone(timezone_name)
        if now_override:
            if now_override.tzinfo is None:
                now_slot = pytz.utc.localize(now_override).astimezone(tz).ceil("15min")
            else:
                now_slot = now_override.astimezone(tz).ceil("15min")
        else:
            now_slot = pd.Timestamp.now(tz=tz).floor("15min")

        # 3. Strategy (S-Index & Safety Margins)
        s_index_debug = {}
        effective_load_margin = 1.0
        target_soc_kwh = 0.0

        if mode == "full":
            # Calculate S-Index / Load Inflation
            # Note: Legacy uses static/base factor for load inflation (D1 safety)
            # and dynamic risk factor for target SoC (D2 strategy)

            s_index_cfg = active_config.get("s_index", {})
            base_factor = float(s_index_cfg.get("base_factor", 1.05))

            # Apply learned base factor
            if "s_index_base_factor" in learning_overlays:
                base_factor = float(learning_overlays["s_index_base_factor"])
                # Update cfg copy so functions see the learned value
                s_index_cfg = s_index_cfg.copy()
                s_index_cfg["base_factor"] = base_factor

            # Mode Check: Probabilistic vs Dynamic
            if s_index_cfg.get("mode") == "probabilistic":
                factor, s_debug = calculate_probabilistic_s_index(
                    df,
                    s_index_cfg,
                    float(s_index_cfg.get("max_factor", 1.5)),
                    timezone_name,
                    daily_probabilistic=input_data.get("daily_probabilistic"),
                )
                if factor is not None:
                    effective_load_margin = factor
                else:
                    logger.warning("Probabilistic S-Index failed (using base_factor): %s", s_debug)
                    effective_load_margin = base_factor

                s_index_debug.update(s_debug or {})
            else:
                # Legacy Dynamic Calculation
                factor, s_debug, _ = calculate_dynamic_s_index(
                    df,
                    s_index_cfg,
                    float(s_index_cfg.get("max_factor", 1.5)),
                    timezone_name,
                    fetch_temperature_fn=lambda days, t: fetch_temperature_forecast(
                        days, t, active_config
                    ),
                )
                effective_load_margin = factor if factor is not None else base_factor

                s_index_debug.update(s_debug or {})

            # Calculate Future Risk (D2) for Target SoC
            risk_factor, risk_debug = calculate_future_risk_factor(
                df,
                s_index_cfg,
                timezone_name,
                fetch_temperature_fn=lambda days, t: fetch_temperature_forecast(
                    days, t, active_config
                ),
            )

            # Calculate Dynamic Target SoC
            # Pass raw_factor for weather adjustment (independent of risk level)
            raw_factor_for_weather = risk_debug.get(
                "raw_factor_with_weather", risk_debug.get("raw_factor", 1.0)
            )
            target_soc_pct, target_soc_kwh, soc_debug = calculate_dynamic_target_soc(
                risk_factor,
                active_config.get("battery", {}),
                s_index_cfg,
                raw_factor=raw_factor_for_weather,
            )

            # Extract raw factor from s_debug (handle both naming conventions)
            raw_factor = s_debug.get("raw_factor", s_debug.get("factor_unclamped"))

            s_index_debug = {
                "mode": "decoupled",
                "base_factor": base_factor,
                "effective_load_margin": effective_load_margin,
                "raw_factor": raw_factor,
                "future_risk": risk_debug,
                "target_soc": soc_debug,
            }

            # Apply Safety Margins (PV confidence, Load inflation, Overlays)
            df = apply_safety_margins(df, active_config, learning_overlays, effective_load_margin)
        else:
            # Baseline mode: No safety margins, raw forecasts
            df["adjusted_pv_kwh"] = df["pv_forecast_kwh"]
            df["adjusted_load_kwh"] = df["load_forecast_kwh"]

        # 4. Schedule Water Heating
        # Get water heater daily consumption from HA sensor (Rev K18)
        initial_state = input_data.get("initial_state", {})
        ha_water_today = float(initial_state.get("water_heated_today_kwh", 0.0))
        # Note: Kepler handles water_heating_kw in the MILP.
        # Heuristic fallback removed in REV LCL01.

        # 5. Run Solver (Kepler)
        # CRITICAL: Only pass FUTURE slots to Kepler, starting from NOW with CURRENT real SoC
        # This ensures replanning during the day uses actual battery state, not midnight projection
        initial_state = input_data.get("initial_state", {})

        # Get current real SoC from Home Assistant
        initial_soc_kwh = float(
            initial_state.get("battery_kwh", initial_state.get("battery_soc_kwh", 0.0))
        )
        if initial_soc_kwh == 0.0 and "battery_soc_percent" in initial_state:
            cap = float(active_config.get("battery", {}).get("capacity_kwh", 0.0))
            initial_soc_kwh = (float(initial_state["battery_soc_percent"]) / 100.0) * cap

        logger.info("Pipeline initial_soc_kwh: %.3f (real SoC from HA)", initial_soc_kwh)

        # Filter to FUTURE slots only (>= now_slot)
        # Kepler should optimize from NOW, not from midnight
        future_df = df[df.index >= now_slot].copy()
        if future_df.empty:
            logger.warning("No future slots available for Kepler! Using full DataFrame.")
            future_df = df.copy()
        else:
            logger.info(
                "Kepler: Planning %d future slots starting from %s", len(future_df), now_slot
            )

        kepler_input = planner_to_kepler_input(future_df, initial_soc_kwh)
        kepler_config = config_to_kepler_config(active_config, overrides, kepler_input.slots)

        # Rev O1: Disable water heating in Kepler if no water heater
        if not has_water_heater:
            logger.info("No water heater - disabling water heating optimization")
            kepler_config.water_heating_min_kwh = 0.0
            kepler_config.water_comfort_penalty_sek = 0.0
            kepler_config.water_heating_max_gap_hours = 0.0

        # Rev O1: Constrain battery if no battery system
        if not has_battery:
            logger.info("No battery - disabling battery optimization (charge/discharge disabled)")
            kepler_config.max_charge_power_kw = 0.0
            kepler_config.max_discharge_power_kw = 0.0

        # Rev K18: Pass water heated today to reduce remaining min requirement
        kepler_config.water_heated_today_kwh = ha_water_today

        # Rev K19: Vacation Mode Anti-Legionella
        vacation_cfg = water_cfg.get("vacation_mode", {})
        vacation_enabled = vacation_cfg.get("enabled", False)
        schedule_anti_legionella = False

        # HA entity can override config when ON
        ha_vacation = initial_state.get("vacation_mode", False)
        if ha_vacation:
            vacation_enabled = True

        if vacation_enabled:
            logger.info("Vacation mode enabled - disabling comfort-based water heating")
            # Disable normal comfort-based heating AND top-ups (gap constraint)
            kepler_config.water_heating_min_kwh = 0.0
            kepler_config.water_comfort_penalty_sek = 0.0
            kepler_config.water_heating_max_gap_hours = 0.0  # Disable top-ups

            # Check if anti-legionella cycle is due
            sqlite_path = active_config.get("learning", {}).get(
                "sqlite_path", "data/planner_learning.db"
            )
            last_al = load_last_anti_legionella(sqlite_path)

            # Smart detection: If water was already heated today (≥2 kWh), treat as anti-legionella done
            # This prevents unnecessary heating when vacation mode is just enabled
            if last_al is None and ha_water_today >= 2.0:
                logger.info(
                    "Vacation mode: No prior anti-legionella record, but %.1f kWh already heated today. "
                    "Setting last_anti_legionella_at to today.",
                    ha_water_today,
                )
                save_last_anti_legionella(sqlite_path, now_slot.to_pydatetime())
                last_al = now_slot.to_pydatetime()

            days_since = (
                (now_slot.to_pydatetime().replace(tzinfo=None) - last_al.replace(tzinfo=None)).days
                if last_al
                else 999
            )
            interval_days = int(vacation_cfg.get("anti_legionella_interval_days", 7))

            # Trigger scheduling after 14:00 (when tomorrow's prices are available)
            # and when interval - 1 days have passed (allows scheduling in next 24h)
            if days_since >= (interval_days - 1) and now_slot.hour >= 14:
                duration_hours = float(vacation_cfg.get("anti_legionella_duration_hours", 3.0))
                power_kw = float(water_cfg.get("power_kw", 3.0))
                al_kwh = duration_hours * power_kw
                kepler_config.water_heating_min_kwh = al_kwh
                schedule_anti_legionella = True
                logger.info(
                    "Anti-legionella due: %d days since last (interval=%d). Scheduling %.1f kWh.",
                    days_since,
                    interval_days,
                    al_kwh,
                )
            else:
                logger.debug(
                    "Anti-legionella not due: %d days since last, hour=%d",
                    days_since,
                    now_slot.hour,
                )

        logger.info(
            "Kepler input initial_soc_kwh: %.3f, water_heated_today: %.2f kWh",
            kepler_input.initial_soc_kwh,
            ha_water_today,
        )

        # Target SoC is applied via soft constraint in Kepler solver:
        # - min_soc violation: 1000 SEK/kWh (HARD - don't violate!)
        # - target violation: derived from risk_appetite (SOFT - economics can override)
        # Safety = high penalty (harder to violate), Gambler = low penalty (easier to trade off)
        if mode == "full" and target_soc_kwh > 0:
            kepler_config.target_soc_kwh = target_soc_kwh

            # Target penalty derived from risk_appetite
            RISK_PENALTY_MAP = {
                1: 20.0,  # Safety: Strong incentive to hit target
                2: 14.0,  # Conservative
                3: 8.0,  # Neutral
                4: 5.0,  # Aggressive
                5: 2.0,  # Gambler: Easy to trade off for profit
            }
            risk_appetite = int(s_index_cfg.get("risk_appetite", 3))
            kepler_config.target_soc_penalty_sek = RISK_PENALTY_MAP.get(risk_appetite, 8.0)

        solver = KeplerSolver()
        result = solver.solve(kepler_input, kepler_config)

        if result.slots:
            logger.info(
                "Kepler result: %d slots, first soc_kwh=%.3f",
                len(result.slots),
                result.slots[0].soc_kwh,
            )

            # Rev K19: Save anti-legionella timestamp if scheduled
            if schedule_anti_legionella:
                # Check if water heating was actually planned
                water_slots = [s for s in result.slots if s.water_heat_kw > 0]
                if water_slots:
                    save_last_anti_legionella(sqlite_path, now_slot.to_pydatetime())
                    logger.info("Anti-legionella cycle scheduled, timestamp saved.")

        # Convert result back to DataFrame
        capacity = kepler_config.capacity_kwh
        result_df = kepler_result_to_dataframe(result, capacity, initial_soc_kwh)

        logger.info(
            "result_df first projected_soc_kwh: %.3f",
            result_df.iloc[0]["projected_soc_kwh"] if len(result_df) > 0 else 0.0,
        )

        # Preserve water_heating_kw before merge (Kepler doesn't know about water heating)
        water_heating_series = (
            future_df["water_heating_kw"].copy()
            if "water_heating_kw" in future_df.columns
            else None
        )

        # Merge result back into future_df (not full df!)
        # Kepler only planned future slots, so result_df matches future_df indices
        final_df = future_df.join(result_df, rsuffix="_kepler")

        # Copy ALL columns from result_df to final_df (overwrite existing, add new)
        for col in result_df.columns:
            final_df[col] = result_df[col].values

        # Restore water_heating_kw (it was set in schedule_water_heating but overwritten above)
        if water_heating_series is not None:
            final_df["water_heating_kw"] = water_heating_series

        # 6. Manual Plan
        final_df = apply_manual_plan(final_df, active_config)

        # 7. Apply dynamic soc_target_percent based on actions
        # This sets per-slot targets: Charge blocks → projected end SoC,
        # Export blocks → projected end SoC, Discharge → min_soc, Hold → entry SoC
        final_df = apply_soc_target_percent(final_df, active_config, now_slot)

        # 7. Output & Observability
        # Safety Check: Do not save empty/garbage plan
        if mode == "full" and (final_df.empty or "battery_charge_kw" not in final_df.columns):
            logger.error(
                "Planner generated invalid schedule (empty or missing columns). Aborting save to prevent data loss."
            )
            # This will bubble up to SchedulerService as an error, triggering the smart retry loop
            raise ValueError("Planner generated invalid schedule (safety guard)")

        if save_to_file:
            # Prepare window responsibilities (placeholder, Kepler doesn't return windows yet)
            # We can infer them or leave empty.
            window_responsibilities = []

            # Planner State for debug
            planner_state_debug = {
                "cheap_price_threshold": 0.0,  # Kepler doesn't expose this
                "price_smoothing_tolerance": 0.0,
                "cheap_slot_count": 0,
                "non_cheap_slot_count": 0,
            }

            forecast_meta = {"pv_forecast_days": 2, "weather_forecast_days": 2}  # Estimate

            # Add soc_target to s_index_debug for output
            if mode == "full":
                s_index_debug["soc_target_kwh"] = target_soc_kwh
                s_index_debug["soc_target_percent"] = (
                    target_soc_pct if "target_soc_pct" in dir() else 0.0
                )

            save_schedule_to_json(
                final_df,
                active_config,
                now_slot,
                forecast_meta,
                s_index_debug,
                window_responsibilities,
                planner_state_debug,
            )

            # Rev UI5: Always store plan to slot_plans for performance tracking
            try:
                tz = pytz.timezone(timezone_name)
                sqlite_path = active_config.get("learning", {}).get(
                    "sqlite_path", "data/planner_learning.db"
                )
                store = LearningStore(sqlite_path, tz)
                # Reset index so start_time becomes a column (store_plan expects it)
                plan_df = final_df.reset_index()
                store.store_plan(plan_df)
                logger.debug("Stored plan to slot_plans for performance tracking")
            except Exception as store_err:
                logger.warning("Failed to store plan to slot_plans: %s", store_err)

            # Note: Cache invalidation and WebSocket emit moved to planner_service.py (Rev ARC8)

        return final_df


def generate_schedule(
    input_data: dict[str, Any],
    config: dict[str, Any] | None = None,
    mode: str = "full",
    save_to_file: bool = True,
) -> pd.DataFrame:
    """
    Convenience function to generate a schedule.

    Args:
        input_data: Dictionary with price_data, forecast_data, initial_state
        config: Optional config dict (loads from config.yaml if not provided)
        mode: "full" or "baseline"
        save_to_file: Whether to save schedule.json

    Returns:
        DataFrame with the complete schedule
    """
    if config is None:
        import yaml

        with Path("config.yaml").open() as f:
            config = yaml.safe_load(f)

    pipeline = PlannerPipeline(config)
    return pipeline.generate_schedule(input_data, mode=mode, save_to_file=save_to_file)
