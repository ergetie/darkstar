"""
Planner Pipeline

Main orchestrator for the modular planner pipeline.
Coordinates Input → Strategy → Solver → Output flow.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pandas as pd
import pytz

if TYPE_CHECKING:
    from datetime import datetime

from backend.core.version import get_version
from backend.learning.store import LearningStore
from planner.errors import PlannerError, PlannerErrorCode
from planner.inputs.data_prep import apply_safety_margins, prepare_df
from planner.inputs.learning import load_learning_overlays
from planner.inputs.weather import fetch_temperature_forecast
from planner.output.schedule import save_schedule_to_json
from planner.output.soc_target import apply_soc_target_percent
from planner.preflight import run_preflight
from planner.solver.adapter import (
    config_to_kepler_config,
    kepler_result_to_dataframe,
    planner_to_kepler_input,
)
from planner.solver.kepler import KeplerSolver
from planner.strategy.manual_plan import apply_manual_plan
from planner.strategy.s_index import (
    calculate_dynamic_s_index,
    calculate_probabilistic_s_index,
    calculate_safety_floor,
)
from planner.vacation_state import load_last_anti_legionella, save_last_anti_legionella

logger = logging.getLogger("darkstar.planner")


def _calculate_excess_pv_flags(
    kepler_slots: list[Any],
    water_heaters: list[Any],
    ev_chargers: list[Any],
    df: pd.DataFrame,
) -> list[bool]:
    """Pre-calculate per-slot excess PV flags from raw forecasts.

    excess[t] = max(0, pv_forecast[t] - load_forecast[t] - min_water_heat_forecast[t] - min_ev_forecast[t]) > 0

    Returns list of booleans, one per slot.
    """

    T = len(kepler_slots)
    if T == 0:
        return []

    slot_hours_list: list[float] = []
    for s in kepler_slots:
        duration = (s.end_time - s.start_time).total_seconds() / 3600.0
        slot_hours_list.append(duration)

    avg_slot_hours = sum(slot_hours_list) / len(slot_hours_list) if slot_hours_list else 0.25

    # Minimum water heating per slot (sum across all heaters, min_kwh_per_day spread evenly)
    min_water_heat_per_slot = 0.0
    for wh in water_heaters:
        kwh_per_slot = wh.power_kw * avg_slot_hours
        if kwh_per_slot > 0:
            min_water_heat_per_slot += wh.min_kwh_per_day / (24.0 / avg_slot_hours)

    # Minimum EV charging per slot
    min_ev_per_slot = 0.0
    for ev in ev_chargers:
        if ev.plugged_in and ev.max_power_kw > 0:
            min_ev_per_slot += ev.max_power_kw * avg_slot_hours

    flags: list[bool] = []
    for t in range(T):
        pv_kwh = kepler_slots[t].pv_kwh
        load_kwh = kepler_slots[t].load_kwh
        excess = pv_kwh - load_kwh - min_water_heat_per_slot - min_ev_per_slot
        flags.append(excess > 0)

    return flags


def calculate_ev_deadline(departure_time: str, now: datetime, timezone: str) -> datetime | None:
    """
    Calculate the next occurrence of departure time from current time.

    REV K25 Phase 3: Deadline calculation for EV charging constraint.

    Args:
        departure_time: Time string in "HH:MM" format (24-hour)
        now: Current datetime (timezone-aware)
        timezone: IANA timezone name (e.g., "Europe/Stockholm")

    Returns:
        Timezone-aware datetime of the next deadline, or None if departure_time is invalid/empty

    Examples:
        - now=15:00, departure="07:00" -> tomorrow 07:00 (next day)
        - now=06:00, departure="07:00" -> today 07:00 (1 hour from now)
        - now=09:00, departure="07:00" -> tomorrow 07:00 (next day, for following day)
    """
    if not departure_time:
        return None

    # Handle integer minutes-since-midnight (defensive fallback for YAML 1.1 sexagesimal misparse)
    if isinstance(departure_time, int):
        if 0 <= departure_time <= 1439:
            departure_time = f"{departure_time // 60:02d}:{departure_time % 60:02d}"
        else:
            logger.warning(f"Invalid departure time integer: {departure_time} (must be 0-1439)")
            return None

    try:
        # Parse the departure time
        hour, minute = map(int, departure_time.split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            logger.warning(f"Invalid departure time format: {departure_time}")
            return None
    except (ValueError, AttributeError):
        logger.warning(f"Failed to parse departure time: {departure_time}")
        return None

    # Get timezone
    try:
        tz = pytz.timezone(timezone)
    except pytz.UnknownTimeZoneError:
        logger.warning(f"Unknown timezone: {timezone}, using UTC")
        tz = pytz.UTC

    # Ensure 'now' is timezone-aware
    if now.tzinfo is None:
        now = tz.localize(now)

    # Create deadline for today
    today_deadline = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # If today's deadline has passed, use tomorrow
    if today_deadline <= now:
        from datetime import timedelta

        deadline = today_deadline + timedelta(days=1)
        logger.debug(f"EV deadline: {departure_time} has passed today, using tomorrow: {deadline}")
    else:
        deadline = today_deadline
        logger.debug(f"EV deadline: {departure_time} is today: {deadline}")

    return deadline


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
        # REV F66b: Check new ARC15 water_heaters[] array, fallback to legacy water_heating
        if system_cfg.get("has_water_heater", True):
            water_heaters = self.config.get("water_heaters", [])
            if water_heaters:
                # New ARC15 structure - sum power from enabled heaters
                enabled_heaters = [wh for wh in water_heaters if wh.get("enabled", True)]
                power_kw = sum(float(wh.get("power_kw", 0.0)) for wh in enabled_heaters)
            else:
                # Legacy structure
                power_kw = float(water_cfg.get("power_kw", 0.0))

            if power_kw <= 0:
                logger.warning(
                    "Config warning: has_water_heater=true but water heater power is 0. "
                    "Water heating optimization is disabled."
                )

        # Solar: WARNING only (doesn't break system, just zeros PV forecasts)
        # REV F66b: Check new solar_arrays[] array, fallback to legacy solar_array
        if system_cfg.get("has_solar", True):
            solar_arrays = system_cfg.get("solar_arrays", [])
            if solar_arrays:
                # New structure - sum kwp from all arrays
                kwp = sum(float(sa.get("kwp", 0.0)) for sa in solar_arrays)
            else:
                # Legacy structure
                solar_cfg = system_cfg.get("solar_array", {})
                kwp = float(solar_cfg.get("kwp", 0.0))

            if kwp <= 0:
                logger.warning(
                    "Config warning: has_solar=true but solar kwp is 0. PV forecasts will be zero."
                )

    def _apply_overrides(self, config: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        """Apply configuration overrides recursively."""
        new_config = copy.deepcopy(config)

        def update_recursive(d: dict[str, Any], u: dict[str, Any]) -> dict[str, Any]:
            for k, v in u.items():
                if isinstance(v, dict):
                    d[k] = update_recursive(d.get(k, {}), v)  # type: ignore[arg-type]
                else:
                    d[k] = v
            return d

        return update_recursive(new_config, overrides)

    async def generate_schedule(
        self,
        input_data: dict[str, Any],
        overrides: dict[str, Any] | None = None,
        mode: str = "full",
        save_to_file: bool = True,
        record_training_episode: bool = False,
        now_override: datetime | None = None,
        ev_plug_override_charger_id: str | None = None,
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
        logger.info("Darkstar %s — PlannerPipeline.generate_schedule(mode=%s)", get_version(), mode)

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
            learning_overlays = await load_learning_overlays(active_config.get("learning", {}))

        # Rev WH2: Load previous schedule to check for active water heating (Mid-block locking)
        previous_schedule: list[dict[str, Any]] = []
        try:
            import json

            schedule_path = Path("schedule.json")
            if schedule_path.exists():
                with schedule_path.open() as f:
                    data = json.load(f)
                    previous_schedule = data.get("schedule", [])
        except Exception as e:
            logger.warning("Failed to load previous schedule for water locking: %s", e)

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
                now_slot = pd.Timestamp(now_override, tz="UTC").tz_convert(tz).ceil("15min")
            else:
                now_slot = pd.Timestamp(now_override).tz_convert(tz).ceil("15min")
        else:
            now_slot = pd.Timestamp.now(tz=tz).floor("15min")

        # Per-device mid-block detection (task 3.1)
        # force_water_by_heater: heater_id → set of timestamps to force ON
        water_heaters_cfg: list[dict[str, Any]] = active_config.get("water_heaters", [])
        enabled_heater_ids: list[str] = [
            str(wh.get("id", ""))
            for wh in water_heaters_cfg
            if wh.get("enabled", True) and wh.get("id")
        ]
        force_water_by_heater: dict[str, set[pd.Timestamp]] = {d: set() for d in enabled_heater_ids}

        if previous_schedule and enabled_heater_ids:
            try:
                now_iso = now_slot.isoformat()
                current_idx = -1
                i: int = 0
                s: dict[str, Any]
                for i, s in enumerate(previous_schedule):
                    if s["start_time"].startswith(now_iso[:16]):  # type: ignore[union-attr]
                        current_idx = i
                        break

                if current_idx >= 0:
                    curr: dict[str, Any] = previous_schedule[current_idx]
                    curr_water_heaters: dict[str, Any] = curr.get("water_heaters", {})

                    for heater_id in enabled_heater_ids:
                        # Check if this specific heater is currently active
                        heater_data: dict[str, Any] = curr_water_heaters.get(heater_id, {})
                        currently_heating = float(heater_data.get("heating_kw", 0.0)) > 0

                        if currently_heating:
                            logger.info(
                                "Mid-block lock: heater %s is active - locking remaining slots.",
                                heater_id,
                            )
                            for j in range(current_idx, len(previous_schedule)):
                                slot_s = previous_schedule[j]
                                slot_water_heaters: dict[str, Any] = slot_s.get("water_heaters", {})
                                slot_heater: dict[str, Any] = slot_water_heaters.get(heater_id, {})
                                slot_heating = float(slot_heater.get("heating_kw", 0.0)) > 0
                                if slot_heating:
                                    ts = pd.Timestamp(slot_s["start_time"]).astimezone(tz)  # type: ignore[arg-type,index]
                                    force_water_by_heater[heater_id].add(ts)
                                else:
                                    break
            except Exception as e:
                logger.warning("Failed to determine per-device forced water slots: %s", e)

        # 3. Strategy (S-Index & Safety Margins)
        s_index_debug: dict[str, Any] = {}
        effective_load_margin = 1.0
        target_soc_kwh = 0.0
        target_soc_pct = 0.0
        s_index_cfg: dict[str, Any] = {}

        if mode == "full":
            # Calculate S-Index / Load Inflation
            # Note: Legacy uses static/base factor for load inflation (D1 safety)
            # and dynamic risk factor for target SoC (D2 strategy)

            s_index_cfg = active_config.get("s_index", {}) or {}
            base_factor = float(s_index_cfg.get("base_factor", 1.05))

            # Apply learned base factor
            if "s_index_base_factor" in learning_overlays:
                base_factor = float(learning_overlays["s_index_base_factor"])
                # Update cfg copy so functions see the learned value
                s_index_cfg = s_index_cfg.copy()
                s_index_cfg["base_factor"] = base_factor

            # Mode Check: Probabilistic vs Dynamic
            s_debug: dict[str, Any] = {}
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
                factor, s_debug, _ = await calculate_dynamic_s_index(
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

            # Rev K23 Phase 3: Physical Deficit Logic
            # Replaces legacy Risk Factor + Dynamic Target SoC logic
            # Temporal Safety Floor: Build full forecast DataFrame beyond price horizon
            from planner.inputs.data_prep import build_forecast_dataframe

            price_horizon_end = df.index[-1] if len(df) > 0 else None
            full_forecast_data = cast(
                "list[dict[str, Any]]",
                input_data.get("extended_forecast_data") or input_data.get("forecast_data") or [],
            )
            full_forecast_df = build_forecast_dataframe(full_forecast_data, timezone_name)

            soc_debug: dict[str, Any] = {}
            target_soc_kwh, soc_debug = calculate_safety_floor(
                df,
                active_config.get("battery", {}),
                s_index_cfg,
                timezone_name,
                fetch_temperature_fn=lambda days, t: fetch_temperature_forecast(
                    days, t, active_config
                ),
                full_forecast_df=full_forecast_df,
                price_horizon_end=price_horizon_end,
            )

            # Derive percentage for UI/Legacy compatibility
            battery_cap = float(active_config.get("battery", {}).get("capacity_kwh", 13.5) or 13.5)
            target_soc_pct = (target_soc_kwh / battery_cap) * 100.0 if battery_cap > 0 else 0.0
            raw_factor: float | None = None

            logger.info(
                "S-Index: Mode=temporal_deficit, TemporalDeficit=%.2f kWh, Floor=%.2f kWh (%.2f%%), Risk=%d",
                soc_debug.get("temporal_deficit_kwh", 0.0),
                target_soc_kwh,
                target_soc_pct,
                s_index_cfg.get("risk_appetite", 3),
            )

            # Extract raw factor from s_debug (handle both naming conventions)
            raw_factor = s_index_debug.get("raw_factor", s_index_debug.get("factor_unclamped"))  # type: ignore[assignment]

            s_index_debug = {
                "mode": "physical_deficit",
                "base_factor": base_factor,
                "effective_load_margin": effective_load_margin,
                "raw_factor": raw_factor,  # Kept for visibility of D1 margin
                "avg_deficit": s_index_debug.get("avg_deficit"),
                "temp_adjustment": s_index_debug.get("temp_adjustment"),
                "mean_temperature_c": s_index_debug.get("mean_temperature_c"),
                "safety_floor": soc_debug,
            }

            # Apply Safety Margins (PV confidence, Load inflation, Overlays)
            df = apply_safety_margins(df, active_config, learning_overlays, effective_load_margin)
        else:
            # Baseline mode: No safety margins, raw forecasts
            df["adjusted_pv_kwh"] = df["pv_forecast_kwh"]
            df["adjusted_load_kwh"] = df["load_forecast_kwh"]

        # 4. Per-device today's energy tracking (task 3.2)
        initial_state = input_data.get("initial_state", {})
        # Look for per-device states first, fall back to distributing aggregate
        ha_water_states_raw: list[dict[str, Any]] = initial_state.get("water_heater_states", [])
        ha_water_today_total = float(initial_state.get("water_heated_today_kwh", 0.0))

        # Build per-device heated_today lookup from HA states or aggregate fallback
        water_heated_today_by_id: dict[str, float] = {}
        if ha_water_states_raw:
            for wh_state in ha_water_states_raw:
                hid = str(wh_state.get("id", ""))
                if hid:
                    water_heated_today_by_id[hid] = float(wh_state.get("heated_today_kwh", 0.0))
        elif ha_water_today_total > 0 and len(enabled_heater_ids) == 1:
            # Single heater: assign total to it
            water_heated_today_by_id[enabled_heater_ids[0]] = ha_water_today_total

        # 5. Run Solver (Kepler)
        # CRITICAL: Only pass FUTURE slots to Kepler, starting from NOW with CURRENT real SoC
        # This ensures replanning during the day uses actual battery state, not midnight projection

        # Get current real SoC from Home Assistant
        initial_soc_kwh = float(
            initial_state.get("battery_kwh", initial_state.get("battery_soc_kwh", 0.0))
        )
        if initial_soc_kwh == 0.0 and "battery_soc_percent" in initial_state:
            cap = float(active_config.get("battery", {}).get("capacity_kwh", 0.0))
            initial_soc_kwh = (float(initial_state["battery_soc_percent"]) / 100.0) * cap

        logger.info("Pipeline initial_soc_kwh: %.3f (real SoC from HA)", initial_soc_kwh)

        # Filter to FUTURE slots only (>= now_slot)
        future_df = df[df.index >= now_slot].copy()
        if future_df.empty:
            logger.warning("No future slots available for Kepler! Using full DataFrame.")
            future_df = df.copy()
        else:
            logger.info(
                "Kepler: Planning %d future slots starting from %s", len(future_df), now_slot
            )

        # Map per-device forced timestamps to Kepler slot indices (task 3.1)
        force_on_slots_by_heater: dict[str, list[int]] = {}
        for heater_id, forced_ts in force_water_by_heater.items():
            if not forced_ts:
                continue
            indices: list[int] = []
            for idx, (ts, _) in enumerate(future_df.iterrows()):
                if ts in forced_ts:
                    indices.append(idx)
            if indices:
                force_on_slots_by_heater[heater_id] = indices
                logger.info(
                    "Mid-block lock: heater %s forcing %d slots ON",
                    heater_id,
                    len(indices),
                )

        # Build per-device water heater states for the adapter (task 3.3)
        water_heater_states: list[dict[str, Any]] = []
        for heater_id in enabled_heater_ids:
            water_heater_states.append(
                {
                    "id": heater_id,
                    "heated_today_kwh": water_heated_today_by_id.get(heater_id, 0.0),
                    "force_on_slots": force_on_slots_by_heater.get(heater_id),
                }
            )

        # Get max DC input for PV clipping
        max_dc_input_kw = system_cfg.get("inverter", {}).get("max_dc_input_kw")
        if max_dc_input_kw is not None:
            max_dc_input_kw = float(max_dc_input_kw)

        kepler_input = planner_to_kepler_input(future_df, initial_soc_kwh, max_dc_input_kw)
        kepler_config = config_to_kepler_config(
            active_config,
            overrides,
            kepler_input.slots,
            water_heater_states=water_heater_states,  # task 3.3
        )

        # Pre-calculate excess PV slot flags from raw forecasts (task 3.1)
        if len(kepler_config.excess_pv_priority) > 0 and len(kepler_input.slots) > 0:
            excess_pv_flags = _calculate_excess_pv_flags(
                kepler_input.slots,
                kepler_config.water_heaters,
                kepler_config.ev_chargers,
                future_df,
            )
            kepler_config.excess_pv_slots = excess_pv_flags
            logger.info(
                "Excess PV: %d/%d slots have excess PV (sinks=%s)",
                sum(excess_pv_flags),
                len(excess_pv_flags),
                [e.type for e in kepler_config.excess_pv_priority],
            )

        # Rev O1: Disable water heating in Kepler if no water heater (task 3.4)
        if not has_water_heater:
            logger.info("No water heater - disabling water heating optimization")
            kepler_config.water_heaters = []

        # Rev O1: Constrain battery if no battery system
        if not has_battery:
            logger.info("No battery - disabling battery optimization (charge/discharge disabled)")
            kepler_config.max_charge_power_kw = 0.0
            kepler_config.max_discharge_power_kw = 0.0

        # Per-device EV state: build EVChargerInput list for Kepler
        has_ev_charger = system_cfg.get("has_ev_charger", False)
        if has_ev_charger:
            ev_charger_states_raw: list[dict[str, Any]] = initial_state.get("ev_charger_states", [])
            ev_chargers_cfg: list[dict[str, Any]] = active_config.get("ev_chargers", [])
            timezone_name = active_config.get("timezone", "Europe/Stockholm")

            # Calculate per-device deadlines and attach to state dicts
            ev_charger_states_with_deadline: list[dict[str, Any]] = []
            for ev_cfg_item in ev_chargers_cfg:
                if not ev_cfg_item.get("enabled", True):
                    continue
                charger_id = ev_cfg_item.get("id", "")
                default_state: dict[str, Any] = {}
                # Find matching HA state
                ha_state = next(
                    (s for s in ev_charger_states_raw if s.get("id") == charger_id),
                    default_state,
                )
                departure_time = ev_cfg_item.get("departure_time", "")
                deadline = None
                if departure_time and ha_state.get("plugged_in", False):
                    deadline = calculate_ev_deadline(
                        departure_time,
                        now_slot.to_pydatetime(),
                        timezone_name,
                    )
                    if deadline:
                        logger.info(
                            "EV %s: SoC=%.1f%%, Plugged=%s, Departure=%s, Deadline=%s",
                            charger_id,
                            ha_state.get("soc_percent", 0.0),
                            ha_state.get("plugged_in", False),
                            departure_time,
                            deadline.strftime("%Y-%m-%d %H:%M"),
                        )
                    else:
                        logger.info(
                            "EV %s: SoC=%.1f%%, Plugged=%s",
                            charger_id,
                            ha_state.get("soc_percent", 0.0),
                            ha_state.get("plugged_in", False),
                        )
                ev_charger_states_with_deadline.append(
                    {
                        "id": charger_id,
                        "soc_percent": ha_state.get("soc_percent", 0.0),
                        "plugged_in": ha_state.get("plugged_in", False),
                        "deadline": deadline,
                    }
                )

            # Rebuild kepler_config with per-device EV charger inputs
            from planner.solver.adapter import build_ev_charger_inputs

            kepler_config.ev_chargers = build_ev_charger_inputs(
                ev_chargers_cfg, ev_charger_states_with_deadline
            )

            # Rev K19: Vacation Mode Anti-Legionella
        vacation_cfg = water_cfg.get("vacation_mode", {})
        vacation_enabled = vacation_cfg.get("enabled", False)
        schedule_anti_legionella = False
        sqlite_path: str = ""

        # HA entity can override config when ON
        ha_vacation = initial_state.get("vacation_mode", False)
        if ha_vacation:
            vacation_enabled = True

        if vacation_enabled:
            logger.info("Vacation mode enabled - disabling comfort-based water heating")
            # Disable water heating (clear the per-device list)
            kepler_config.water_heaters = []
            kepler_config.water_heating_max_gap_hours = 0.0

            # Check if anti-legionella cycle is due
            sqlite_path = active_config.get("learning", {}).get(
                "sqlite_path", "data/planner_learning.db"
            )
            last_al = load_last_anti_legionella(sqlite_path)

            # Smart detection: If water was already heated today (≥2 kWh), treat as done
            ha_water_today_total = (
                sum(water_heated_today_by_id.values())
                if water_heated_today_by_id
                else ha_water_today_total
            )
            if last_al is None and ha_water_today_total >= 2.0:
                logger.info(
                    "Vacation mode: No prior anti-legionella record, but %.1f kWh already heated today. "
                    "Setting last_anti_legionella_at to today.",
                    ha_water_today_total,
                )
                save_last_anti_legionella(sqlite_path, now_slot.to_pydatetime())
                last_al = now_slot.to_pydatetime()

            days_since = (
                (now_slot.to_pydatetime().replace(tzinfo=None) - last_al.replace(tzinfo=None)).days
                if last_al
                else 999
            )
            interval_days = int(vacation_cfg.get("anti_legionella_interval_days", 7))

            if days_since >= (interval_days - 1) and now_slot.hour >= 14:
                duration_hours = float(vacation_cfg.get("anti_legionella_duration_hours", 3.0))
                # Rebuild per-device water heaters for anti-legionella
                # Each heater runs for duration_hours, min_kwh = power_kw * duration_hours
                from planner.solver.adapter import build_water_heater_inputs

                al_heaters = build_water_heater_inputs(
                    water_heaters_cfg, active_config.get("water_heating", {}), water_heater_states
                )
                for h in al_heaters:
                    h.min_kwh_per_day = h.power_kw * duration_hours
                kepler_config.water_heaters = al_heaters
                al_kwh_total = sum(h.min_kwh_per_day for h in al_heaters)
                schedule_anti_legionella = True
                logger.info(
                    "Anti-legionella due: %d days since last (interval=%d). Scheduling %.1f kWh across %d heaters.",
                    days_since,
                    interval_days,
                    al_kwh_total,
                    len(al_heaters),
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
            ha_water_today_total,
        )

        # Target SoC is applied via soft constraint in Kepler solver:
        # - min_soc violation: 1000 SEK/kWh (HARD - don't violate!)
        # - target violation: derived from risk_appetite (SOFT - economics can override)
        # Safety = high penalty (harder to violate), Gambler = low penalty (easier to trade off)
        if mode == "full" and target_soc_kwh > 0:
            kepler_config.target_soc_kwh = target_soc_kwh

            # Target penalty derived from risk_appetite
            RISK_PENALTY_MAP = {
                1: 200.0,  # Safety: Strong incentive to hit target
                2: 200.0,
                3: 200.0,
                4: 200.0,
                5: 200.0,
            }
            risk_appetite = int(s_index_cfg.get("risk_appetite", 3))
            kepler_config.target_soc_penalty_sek = RISK_PENALTY_MAP.get(risk_appetite, 8.0)

        run_preflight(input_data, active_config)

        solver = KeplerSolver()
        result = await asyncio.to_thread(solver.solve, kepler_input, kepler_config)

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

        if len(result_df) != len(future_df):
            logger.error(
                "Result merge length mismatch: result_df=%d, future_df=%d — "
                "possible duplicate timestamps in price input",
                len(result_df),
                len(future_df),
            )

        # Copy ALL columns from result_df to final_df (overwrite existing, add new)
        # Use index-aligned assignment (not .values) to avoid ValueError on length mismatch
        for col in result_df.columns:
            final_df[col] = result_df[col]

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
            raise PlannerError(
                code=PlannerErrorCode.INVALID_SCHEDULE,
                details={
                    "solver_status": result.status_msg if result else "unknown",
                    "initial_soc_kwh": initial_soc_kwh,
                    "max_soc_kwh": kepler_config.capacity_kwh
                    * kepler_config.max_soc_percent
                    / 100.0,
                    "capacity_kwh": kepler_config.capacity_kwh,
                },
            )

        if save_to_file:
            # Prepare window responsibilities (placeholder, Kepler doesn't return windows yet)
            # We can infer them or leave empty.
            window_responsibilities: list[dict[str, Any]] = []

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
                s_index_debug["soc_target_percent"] = target_soc_pct

            await save_schedule_to_json(
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
                await store.store_plan(plan_df)
                logger.debug("Stored plan to slot_plans for performance tracking")
            except Exception as store_err:
                logger.warning("Failed to store plan to slot_plans: %s", store_err)

            # Note: Cache invalidation and WebSocket emit moved to planner_service.py (Rev ARC8)

        return final_df


async def generate_schedule(
    input_data: dict[str, Any],
    config: dict[str, Any] | None = None,
    mode: str = "full",
    save_to_file: bool = True,
    ev_plug_override_charger_id: str | None = None,
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

    config_dict: dict[str, Any] = config or {}
    pipeline = PlannerPipeline(config_dict)
    return await pipeline.generate_schedule(
        input_data,
        mode=mode,
        save_to_file=save_to_file,
        ev_plug_override_charger_id=ev_plug_override_charger_id,
    )
