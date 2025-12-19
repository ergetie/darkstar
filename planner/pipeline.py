"""
Planner Pipeline

Main orchestrator for the modular planner pipeline.
Coordinates Input → Strategy → Solver → Output flow.
"""

from __future__ import annotations

import logging
import copy
from typing import Any, Dict, Optional
from datetime import datetime

import pandas as pd
import pytz

from planner.inputs.data_prep import prepare_df, apply_safety_margins
from planner.inputs.learning import load_learning_overlays
from planner.inputs.weather import fetch_temperature_forecast
from planner.strategy.s_index import (
    calculate_dynamic_s_index,
    calculate_probabilistic_s_index,
    calculate_future_risk_factor,
    calculate_dynamic_target_soc,
)
from planner.strategy.windows import identify_windows
from planner.strategy.manual_plan import apply_manual_plan
from planner.scheduling.water_heating import schedule_water_heating
from planner.solver.adapter import (
    planner_to_kepler_input,
    config_to_kepler_config,
    kepler_result_to_dataframe,
)
from planner.solver.kepler import KeplerSolver
from planner.output.schedule import save_schedule_to_json
from planner.output.soc_target import apply_soc_target_percent

logger = logging.getLogger("darkstar.planner")


class PlannerPipeline:
    """
    Orchestrator for the modular planner pipeline.

    Modes:
        - "full": Aurora overlays + Strategy + Kepler (production)
        - "baseline": Kepler only, no Aurora overlays (for A/B comparison)
    """

    def __init__(self, config: Dict[str, Any]):
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

    def _apply_overrides(self, config: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
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
        input_data: Dict[str, Any],
        overrides: Optional[Dict[str, Any]] = None,
        mode: str = "full",
        save_to_file: bool = True,
        record_training_episode: bool = False,
        now_override: Optional[datetime] = None,
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

        # 2. Load Inputs
        # Load learning overlays (PV/Load bias, S-Index base)
        learning_overlays = {}
        if mode == "full":
            learning_overlays = load_learning_overlays(active_config.get("learning", {}))

        # Prepare DataFrame (merge prices + forecasts)
        timezone_name = active_config.get("timezone", "Europe/Stockholm")
        df = prepare_df(input_data, timezone_name)

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
        planner_state = {}
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
                if factor is not None:
                    effective_load_margin = factor
                else:
                    effective_load_margin = base_factor

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
            raw_factor_for_weather = risk_debug.get("raw_factor_with_weather", risk_debug.get("raw_factor", 1.0))
            target_soc_pct, target_soc_kwh, soc_debug = calculate_dynamic_target_soc(
                risk_factor, active_config.get("battery", {}), s_index_cfg,
                raw_factor=raw_factor_for_weather
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

        # Identify Windows (Pass 1)
        initial_state = input_data.get("initial_state", {})
        df, window_debug = identify_windows(df, active_config, initial_state, now_slot)

        # 4. Schedule Water Heating
        # Fetch HA water usage from input_data or query DB?
        # Legacy planner queries DB inside _get_daily_water_usage_kwh.
        # But we need HA sensor value. input_data usually contains 'sensors' or similar?
        # Legacy planner calls self._get_home_assistant_water_heating_today() which calls inputs.get_home_assistant_sensor_float
        # We'll assume input_data has it or we skip it for now (or fetch it if we had the helper).
        # For now, let's assume 0.0 if not provided, or check input_data["sensors"] if available.
        ha_water_today = 0.0  # Placeholder, needs integration with HA client if needed

        df = schedule_water_heating(df, active_config, now_slot, ha_water_today)

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
        kepler_config = config_to_kepler_config(active_config, overrides)

        logger.info("Kepler input initial_soc_kwh: %.3f", kepler_input.initial_soc_kwh)

        # Target SoC is applied via soft constraint in Kepler solver
        # (soc_violation penalty = 1000 SEK/kWh + terminal_value incentive)
        # 
        # IMPORTANT: We do NOT raise min_soc_percent globally because:
        # - That would prevent mid-day discharge even when profitable
        # - Soft target allows Kepler to optimize, just incentivizes ending high
        # - MPC replans hourly, so end-of-horizon target naturally guides behavior

        solver = KeplerSolver()
        result = solver.solve(kepler_input, kepler_config)

        if result.slots:
            logger.info(
                "Kepler result: %d slots, first soc_kwh=%.3f",
                len(result.slots),
                result.slots[0].soc_kwh,
            )

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

        return final_df


def generate_schedule(
    input_data: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
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

        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)

    pipeline = PlannerPipeline(config)
    return pipeline.generate_schedule(input_data, mode=mode, save_to_file=save_to_file)
