"""
Kepler MILP Solver

Mixed-Integer Linear Programming solver for optimal battery scheduling.
Migrated from backend/kepler/solver.py during Rev K13 modularization.
"""

import logging
from collections import defaultdict
from datetime import date, timedelta  # Rev WH2
from typing import Any, cast

import pulp  # type: ignore[import,no-redef]

from planner.errors import PlannerError, PlannerErrorCode

from .types import (
    EVChargerInput,
    KeplerConfig,
    KeplerInput,
    KeplerResult,
    KeplerResultSlot,
    WaterHeaterInput,
)

logger = logging.getLogger("darkstar.kepler")

EV_SHORTFALL_PENALTY_DEFAULT = 50.0  # SEK/kWh — soft target-by-time penalty


def _ev_day_energy_terms(
    day: date,
    charger_id: str,
    ev_energy: dict[str, dict[int, Any]],
    surplus_kw: dict[int, Any] | None,
    slots: list[Any],
    slot_hours: list[float],
    T: int,
) -> list[Any]:
    """Energy terms (scheduled + surplus) for one charger on one calendar day.

    Surplus charging counts against the day's quota too (task 4.4) — it isn't
    a free bonus on top of the scheduled allocation.
    """
    terms: list[Any] = [
        ev_energy[charger_id][t] for t in range(T) if slots[t].start_time.date() == day
    ]
    if surplus_kw is not None:
        terms.extend(
            surplus_kw[t] * slot_hours[t] for t in range(T) if slots[t].start_time.date() == day
        )
    return terms


class KeplerSolver:
    def solve(self, input_data: KeplerInput, config: KeplerConfig) -> KeplerResult:
        """Solve the energy scheduling problem using MILP.

        Args:
            input_data: Input data containing slots, initial SoC, etc.
            config: Solver configuration parameters

        Returns:
            KeplerResult with optimized schedule slots and cost information
        """
        """
        Solve the energy scheduling problem using MILP.
        """
        slots = input_data.slots
        T = len(slots)
        if T == 0:
            return KeplerResult(
                slots=[],
                total_cost_sek=0.0,
                is_optimal=True,
                status_msg="No slots to schedule",
            )

        # Calculate slot duration in hours
        slot_hours: list[float] = []
        for s in slots:
            duration = (s.end_time - s.start_time).total_seconds() / 3600.0
            slot_hours.append(duration)

        # Problem Definition
        prob: Any = pulp.LpProblem("KeplerSchedule", pulp.LpMinimize)

        # Variables (all in kWh per slot)
        charge: dict[int, Any] = pulp.LpVariable.dicts("charge_kwh", range(T), lowBound=0.0)  # type: ignore[reportUnknownMemberType]
        discharge: dict[int, Any] = pulp.LpVariable.dicts("discharge_kwh", range(T), lowBound=0.0)  # type: ignore[reportUnknownMemberType]
        grid_import: dict[int, Any] = pulp.LpVariable.dicts("import_kwh", range(T), lowBound=0.0)  # type: ignore[reportUnknownMemberType]
        grid_export: dict[int, Any] = pulp.LpVariable.dicts("export_kwh", range(T), lowBound=0.0)  # type: ignore[reportUnknownMemberType]
        curtailment: dict[int, Any] = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
            "curtailment_kwh", range(T), lowBound=0.0
        )
        load_shedding: dict[int, Any] = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
            "load_shedding_kwh", range(T), lowBound=0.0
        )

        # Water heating as deferrable load (per-device)
        water_heaters: list[WaterHeaterInput] = config.water_heaters
        water_enabled: bool = len(water_heaters) > 0

        # Per-device indexed variables: water_heat[device_id][t], water_start[device_id][t]
        water_heat: dict[str, dict[int, Any]] = {}
        water_start: dict[str, dict[int, Any]] = {}
        # Per-device boost variables: water_boost[device_id][t]
        water_boost: dict[str, dict[int, Any]] = {}
        boost_entry = next(
            (e for e in config.excess_pv_priority if e.type == "water_heater_boost"), None
        )
        boost_enabled = boost_entry is not None
        # Per-device gap-comfort variables: discomfort[device_id][t], gap_over[device_id][t]
        discomfort: dict[str, dict[int, Any]] = {}
        gap_over: dict[str, dict[int, Any]] = {}
        if water_enabled:
            for heater in water_heaters:
                d = heater.id
                safe_d = d.replace("-", "_").replace(".", "_")
                water_heat[d] = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
                    f"water_heat_{safe_d}", range(T), cat="Binary"
                )
                if boost_enabled:
                    water_boost[d] = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
                        f"water_boost_{safe_d}", range(T), cat="Binary"
                    )
                needs_start = (
                    heater.min_spacing_hours > 0 or config.water_block_start_penalty_sek > 0
                )
                if needs_start:
                    water_start[d] = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
                        f"water_start_{safe_d}", range(T), cat="Binary"
                    )
                discomfort[d] = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
                    f"discomfort_{safe_d}", range(T), lowBound=0.0
                )
                gap_over[d] = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
                    f"gap_over_{safe_d}", range(T), lowBound=0.0
                )

        # EV Charging as deferrable load (per-device, multi-charger support)
        # Only create variables for plugged-in chargers
        plugged_chargers: list[EVChargerInput] = [c for c in config.ev_chargers if c.plugged_in]
        ev_any_enabled: bool = len(plugged_chargers) > 0

        # Per-device indexed variables: ev_charge[device_id][t], ev_energy[device_id][t]
        # dict[charger_id -> dict[t -> lp_var]]
        ev_charge: dict[str, dict[int, Any]] = {}
        ev_energy: dict[str, dict[int, Any]] = {}
        # Per-device shortfall variable for soft target-by-time requirement
        ev_shortfall: dict[str, Any] = {}

        for charger in plugged_chargers:
            d = charger.id
            safe_d = d.replace("-", "_").replace(".", "_")
            effective_deadline = charger.deadline or (slots[-1].end_time if slots else None)
            if charger.deadline:
                logger.info(
                    "EV %s: deadline constraint active at %s",
                    d,
                    charger.deadline.strftime("%Y-%m-%d %H:%M"),
                )
            else:
                logger.info("EV %s: no explicit deadline, using end of horizon", d)

            ev_charge[d] = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
                f"ev_charge_{safe_d}", range(T), cat="Binary"
            )
            ev_energy[d] = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
                f"ev_energy_{safe_d}_kwh", range(T), lowBound=0.0
            )
            if charger.required_kwh is not None and effective_deadline is not None:
                ev_shortfall[d] = pulp.LpVariable(f"ev_shortfall_{safe_d}_kwh", lowBound=0.0)

        # any_ev_charging[t]: auxiliary binary - 1 if ANY charger is active in slot t
        any_ev_charging: dict[int, Any]
        if ev_any_enabled:
            any_ev_charging = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
                "any_ev_charging", range(T), cat="Binary"
            )
        else:
            any_ev_charging = dict.fromkeys(range(T), 0)

        # SoC state variables (T+1 states for T slots)

        # SoC state variables (T+1 states for T slots)
        min_soc_kwh: float = config.capacity_kwh * config.min_soc_percent / 100.0
        max_soc_kwh: float = config.capacity_kwh * config.max_soc_percent / 100.0

        soc: dict[int, Any] = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
            "soc_kwh", range(T + 1), lowBound=0.0, upBound=config.capacity_kwh
        )

        # Slack variables
        soc_violation: dict[int, Any] = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
            "soc_violation_kwh", range(T + 1), lowBound=0.0
        )
        soc_overshoot: dict[int, Any] = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
            "soc_overshoot_kwh", range(T + 1), lowBound=0.0
        )
        target_under_violation: Any = pulp.LpVariable(
            "target_under_violation_kwh", lowBound=0.0
        )  # Penalty for being BELOW target at end of horizon
        import_breach: dict[int, Any] = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
            "import_breach_kwh", range(T), lowBound=0.0
        )
        ramp_up: dict[int, Any] = pulp.LpVariable.dicts("ramp_up_kwh", range(T), lowBound=0.0)  # type: ignore[reportUnknownMemberType]
        ramp_down: dict[int, Any] = pulp.LpVariable.dicts("ramp_down_kwh", range(T), lowBound=0.0)  # type: ignore[reportUnknownMemberType]

        # Export floor SoC constraint (gated on enable_export and export_floor_soc_percent)
        export_floor_active = config.enable_export and config.export_floor_soc_percent is not None
        is_exporting: dict[int, Any]
        export_floor_violation: dict[int, Any]
        export_floor_kwh: float = 0.0
        if export_floor_active:
            assert config.export_floor_soc_percent is not None
            export_floor_kwh = config.capacity_kwh * config.export_floor_soc_percent / 100.0
            is_exporting = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
                "is_exporting", range(T), cat="Binary"
            )
            export_floor_violation = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
                "export_floor_violation_kwh", range(T), lowBound=0.0
            )
        else:
            is_exporting = dict.fromkeys(range(T), 0)
            export_floor_violation = dict.fromkeys(range(T), 0)

        # PV routing variables — only created when an AC limit is configured
        pv_routing_active: bool = config.max_inverter_ac_kw is not None
        pv_to_battery: dict[int, Any] = {}
        pv_to_ac: dict[int, Any] = {}
        if pv_routing_active:
            pv_to_battery = cast(
                "dict[int, Any]",
                pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
                    "pv_to_battery_kwh", range(T), lowBound=0.0
                ),
            )
            pv_to_ac = cast(
                "dict[int, Any]",
                pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
                    "pv_to_ac_kwh", range(T), lowBound=0.0
                ),
            )

        # Discomfort variable removed.
        # Per-device "Block Overshoot" variables (soft penalty for massive blocks)
        block_overshoot: dict[str, dict[int, Any]] = {}
        if water_enabled:
            for heater in water_heaters:
                d = heater.id
                safe_d = d.replace("-", "_").replace(".", "_")
                block_overshoot[d] = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
                    f"block_overshoot_{safe_d}", range(T), lowBound=0.0
                )

        # Per-device slack variables for daily minimum soft constraints
        water_min_kwh_violation: dict[str, dict[int, Any]] = {}
        if water_enabled:
            for heater in water_heaters:
                d = heater.id
                safe_d = d.replace("-", "_").replace(".", "_")
                water_min_kwh_violation[d] = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
                    f"water_min_kwh_violation_{safe_d}", range(100), lowBound=0.0
                )

        # Initial SoC Constraint
        initial_soc: float = max(0.0, min(config.capacity_kwh, input_data.initial_soc_kwh))
        prob += soc[0] == initial_soc

        # Excess PV slot flags (pre-calculated from forecasts)
        excess_pv_flags: list[bool] = config.excess_pv_slots
        if excess_pv_flags and len(excess_pv_flags) != T:
            logger.warning(
                "Excess PV flags length (%d) != slot count (%d), ignoring", len(excess_pv_flags), T
            )
            excess_pv_flags = []
        if not excess_pv_flags:
            excess_pv_flags = [False] * T

        # Custom-entity sinks: one variable family per priority-list entry, keyed
        # by str(rank) so the id is stable across a single solve (task 2.4).
        custom_entity_items: list[tuple[str, Any]] = [
            (str(rank), entry)
            for rank, entry in enumerate(config.excess_pv_priority)
            if entry.type == "custom_entity"
        ]
        custom_entity_enabled = len(custom_entity_items) > 0

        # EV surplus sinks: one continuous variable per `ev` priority entry whose
        # charger is plugged in and current-controlled (task 2.5).
        ev_surplus_items: list[tuple[str, EVChargerInput, float]] = []
        for entry in config.excess_pv_priority:
            if entry.type != "ev" or not entry.charger_id:
                continue
            matched_charger = next(
                (
                    c
                    for c in plugged_chargers
                    if c.id == entry.charger_id and c.control_type == "current"
                ),
                None,
            )
            if matched_charger is None:
                continue
            ev_surplus_items.append(
                (entry.charger_id, matched_charger, entry.effective_reward_sek_per_kwh)
            )
        ev_surplus_enabled = len(ev_surplus_items) > 0

        # SoC threshold binary: 1 when battery SoC >= threshold% (gates all sink activation)
        any_sink_active = boost_enabled or custom_entity_enabled or ev_surplus_enabled
        soc_above_threshold: dict[int, Any]
        if any_sink_active:
            soc_above_threshold = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
                "soc_above_threshold", range(T), cat="Binary"
            )
        else:
            soc_above_threshold = dict.fromkeys(range(T), 0)

        custom_entity_active: dict[str, dict[int, Any]] = {}
        for rank_str, _entry in custom_entity_items:
            custom_entity_active[rank_str] = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
                f"custom_entity_active_{rank_str}", range(T), cat="Binary"
            )

        ev_surplus_kw: dict[str, dict[int, Any]] = {}
        for charger_id, charger, _reward in ev_surplus_items:
            safe_id = charger_id.replace("-", "_").replace(".", "_")
            ev_surplus_kw[charger_id] = pulp.LpVariable.dicts(  # type: ignore[reportUnknownMemberType]
                f"ev_surplus_kw_{safe_id}", range(T), lowBound=0.0, upBound=charger.max_power_kw
            )

        # Objective Function Terms
        total_cost: list[Any] = []

        # Penalty constants
        MIN_SOC_PENALTY = 1000.0  # Hard constraint - don't violate min_soc!
        MAX_SOC_PENALTY = 1000.0  # Soft constraint - prefer to stay below max_soc
        EXPORT_FLOOR_PENALTY = 1000.0  # Soft constraint - don't export below floor
        BOOST_REWARD_SEK = boost_entry.effective_reward_sek_per_kwh if boost_entry else 0.0
        # Target penalty comes from config (derived from risk_appetite in pipeline)
        target_soc_penalty = config.target_soc_penalty_sek
        curtailment_penalty = config.curtailment_penalty_sek
        LOAD_SHEDDING_PENALTY = 10000.0
        IMPORT_BREACH_PENALTY = 5000.0

        for t in range(T):
            s: Any = slots[t]
            h: float = slot_hours[t]

            # Water heating load for this slot (kWh) — sum across all per-device heaters
            # Includes both normal and boost heating
            water_load_kwh: Any = (
                pulp.lpSum(
                    (
                        water_heat[heater.id][t]
                        + (water_boost[heater.id][t] if heater.id in water_boost else 0)
                    )
                    * heater.power_kw
                    * h
                    for heater in water_heaters
                )
                if water_enabled
                else 0
            )

            # Boost constrained to excess PV slots only, gated by SoC threshold
            if water_enabled and boost_enabled:
                for heater in water_heaters:
                    if heater.id not in water_boost:
                        continue
                    if not excess_pv_flags[t]:
                        prob += water_boost[heater.id][t] == 0
                    else:
                        prob += water_boost[heater.id][t] <= soc_above_threshold[t]
                        total_cost.append(
                            -BOOST_REWARD_SEK * water_boost[heater.id][t] * heater.power_kw * h
                        )

            # Custom entity: one MILP variable per priority-list entry (task 2.4),
            # each gated by excess PV flag and SoC threshold with its own reward/power_kw.
            if custom_entity_enabled:
                for rank_str, entry in custom_entity_items:
                    var_t = custom_entity_active[rank_str][t]
                    if not excess_pv_flags[t]:
                        prob += var_t == 0
                    else:
                        prob += var_t <= soc_above_threshold[t]
                        total_cost.append(
                            -entry.effective_reward_sek_per_kwh * var_t * entry.power_kw * h
                        )

            # EV surplus: continuous kW per `ev` priority entry (task 2.5), mutually
            # exclusive with scheduled (price-based) charging on the same charger (task 2.6).
            if ev_surplus_enabled:
                for charger_id, charger, reward in ev_surplus_items:
                    var_t = ev_surplus_kw[charger_id][t]
                    prob += var_t <= charger.max_power_kw * (1 - ev_charge[charger_id][t])
                    if not excess_pv_flags[t]:
                        prob += var_t == 0
                    else:
                        prob += var_t <= charger.max_power_kw * soc_above_threshold[t]
                        total_cost.append(-reward * var_t * h)

            # SoC threshold big-M constraint (after soc[t] is defined via battery dynamics)
            # Placed here so soc[t] is available, then linked to boost/custom_entity above.
            # soc_above_threshold[t] = 1  =>  soc[t] >= threshold_kWh
            # soc_above_threshold[t] = 0  =>  no constraint on soc[t]
            if any_sink_active:
                threshold_kwh = config.capacity_kwh * config.excess_pv_soc_threshold_percent / 100.0
                M_soc = config.capacity_kwh
                prob += soc[t] >= threshold_kwh - M_soc * (1 - soc_above_threshold[t])

            # Per-device EV constraints
            for charger in plugged_chargers:
                d = charger.id
                # Energy coupling: binary ON/OFF at max power
                prob += ev_energy[d][t] == ev_charge[d][t] * charger.max_power_kw * h

                # Deadline constraint: zero charging after deadline
                if charger.deadline is not None and s.end_time > charger.deadline:
                    prob += ev_energy[d][t] == 0.0

                # Grid-only constraint: EV cannot charge from battery discharge
                prob += ev_energy[d][t] <= grid_import[t] + s.pv_kwh + 1e-6

            # any_ev_charging[t] linking constraints
            if ev_any_enabled:
                for charger in plugged_chargers:
                    d = charger.id
                    prob += any_ev_charging[t] >= ev_charge[d][t]
                prob += any_ev_charging[t] <= pulp.lpSum(ev_charge[d][t] for d in ev_charge)
                # Discharge blocking: block when any charger active
                M_discharge = config.max_discharge_power_kw * h
                prob += discharge[t] <= (1 - any_ev_charging[t]) * M_discharge

            # Total EV energy in this slot (sum across all plugged-in chargers)
            total_ev_energy_t: Any = (
                pulp.lpSum(ev_energy[d][t] for d in ev_energy) if ev_any_enabled else 0.0
            )

            # Energy Balance Constraint (water, EV, custom entity, and EV surplus loads
            # added to demand side)
            custom_entity_load_kwh: Any = (
                pulp.lpSum(
                    custom_entity_active[rank_str][t] * entry.power_kw * h
                    for rank_str, entry in custom_entity_items
                )
                if custom_entity_enabled
                else 0.0
            )
            ev_surplus_load_kwh: Any = (
                pulp.lpSum(
                    ev_surplus_kw[charger_id][t] * h for charger_id, _, _ in ev_surplus_items
                )
                if ev_surplus_enabled
                else 0.0
            )

            # Limit total excess PV priority sink energy to net excess PV (PV minus
            # house load minus planned battery charging) to prevent grid imports
            # from powering these sinks while appearing to be "free" surplus, and
            # to stop sinks from collecting the surplus reward while grid power
            # covers the battery (economic loophole).
            if excess_pv_flags[t]:
                net_excess_kwh = max(0.0, s.pv_kwh - s.load_kwh)
                sink_terms: list[Any] = []
                if water_enabled:
                    for heater in water_heaters:
                        if heater.id in water_boost:
                            sink_terms.append(water_boost[heater.id][t] * heater.power_kw * h)
                if custom_entity_enabled:
                    for rank_str, entry in custom_entity_items:
                        sink_terms.append(custom_entity_active[rank_str][t] * entry.power_kw * h)
                if ev_surplus_enabled:
                    for charger_id, _, _ in ev_surplus_items:
                        sink_terms.append(ev_surplus_kw[charger_id][t] * h)

                if sink_terms:
                    prob += pulp.lpSum(sink_terms) + charge[t] <= net_excess_kwh
            prob += (
                s.load_kwh
                + water_load_kwh
                + total_ev_energy_t
                + custom_entity_load_kwh
                + ev_surplus_load_kwh
                + charge[t]
                + grid_export[t]
                + curtailment[t]
                == s.pv_kwh + discharge[t] + grid_import[t] + load_shedding[t]
            )

            # Per-device block start detection (task 2.7)
            if water_enabled:
                for heater in water_heaters:
                    d = heater.id
                    if d in water_start:
                        if t == 0:
                            prob += water_start[d][t] == water_heat[d][t]
                        else:
                            prob += water_start[d][t] >= water_heat[d][t] - water_heat[d][t - 1]

            # Per-device mid-block locking (task 2.8)
            if water_enabled:
                for heater in water_heaters:
                    d = heater.id
                    if heater.force_on_slots:
                        for t_idx in heater.force_on_slots:
                            if 0 <= t_idx < T:
                                prob += water_heat[d][t_idx] == 1

            # Battery Dynamics Constraint
            prob += soc[t + 1] == soc[t] + charge[t] * config.charge_efficiency - discharge[t] / (
                config.discharge_efficiency if config.discharge_efficiency > 0 else 1.0
            )

            # Power Limits
            max_chg_kwh: float = config.max_charge_power_kw * h
            max_dis_kwh: float = config.max_discharge_power_kw * h

            prob += charge[t] <= max_chg_kwh
            prob += discharge[t] <= max_dis_kwh

            if config.max_export_power_kw is not None:
                prob += grid_export[t] <= config.max_export_power_kw * h

            if config.max_import_power_kw is not None:
                prob += grid_import[t] <= config.max_import_power_kw * h

            # Inverter AC output limit with PV routing (dc_coupled / ac_coupled)
            if pv_routing_active:
                inverter_ac_kwh: float = cast("float", config.max_inverter_ac_kw) * h
                # PV balance: all forecast PV routes to battery (DC), AC, or curtailment
                prob += pv_to_battery[t] + pv_to_ac[t] + curtailment[t] == s.pv_kwh
                # pv_to_battery is a sub-flow of total charge (can't exceed what the battery accepts)
                prob += pv_to_battery[t] <= charge[t]
                if config.inverter_topology == "ac_coupled":
                    # Battery charging also crosses the AC inverter
                    prob += pv_to_ac[t] + pv_to_battery[t] + discharge[t] <= inverter_ac_kwh
                else:
                    # DC-coupled (default): PV-to-battery bypasses the AC stage
                    prob += pv_to_ac[t] + discharge[t] <= inverter_ac_kwh

            # Soft Grid Import Limit
            if config.grid_import_limit_kw is not None:
                limit_kwh: float = config.grid_import_limit_kw * h
                prob += grid_import[t] <= limit_kwh + import_breach[t]

            # Rev E4: Strict Export Toggle
            if not config.enable_export:
                prob += grid_export[t] == 0

            # Export floor SoC constraint (big-M formulation)
            if export_floor_active:
                M_export = (
                    config.max_export_power_kw
                    if config.max_export_power_kw is not None
                    else config.max_discharge_power_kw
                ) * h
                prob += grid_export[t] <= M_export * is_exporting[t]
                prob += soc[t + 1] >= (
                    export_floor_kwh * is_exporting[t]
                    + min_soc_kwh * (1 - is_exporting[t])
                    - export_floor_violation[t]
                )

            # Ramping Constraints
            if t > 0:
                prob += (charge[t] - discharge[t]) - (charge[t - 1] - discharge[t - 1]) == ramp_up[
                    t
                ] - ramp_down[t]
            else:
                prob += ramp_up[t] == 0
                prob += ramp_down[t] == 0

            # Objective Terms
            # Wear cost modeling: Apply 50% of config value per action (charge OR discharge)
            # so that a full cycle (charge + discharge) costs exactly config.wear_cost_sek_per_kwh
            slot_wear_cost: Any = (charge[t] + discharge[t]) * config.wear_cost_sek_per_kwh * 0.5
            slot_import_cost: Any = grid_import[t] * s.import_price_sek_kwh
            effective_export_price: float = (
                s.export_price_sek_kwh - config.export_threshold_sek_per_kwh
            )
            slot_export_revenue: Any = grid_export[t] * effective_export_price
            slot_ramping_cost: Any = (
                (ramp_up[t] + ramp_down[t]) / h
            ) * config.ramping_cost_sek_per_kw
            # Decision 6 (#16): prefer curtailment over loss-making export — when
            # exporting would cost money (effective_export_price <= 0), curtailing
            # is free so the solver never pays the grid to export. Only relevant
            # when export is actually possible; otherwise curtailment cost keeps
            # steering surplus PV toward battery/EV/water use as before.
            slot_curtailment_cost: Any = (
                curtailment[t] * curtailment_penalty
                if not config.enable_export or effective_export_price > 0
                else 0.0
            )
            slot_shedding_cost: Any = load_shedding[t] * LOAD_SHEDDING_PENALTY
            slot_import_breach_cost: Any = import_breach[t] * IMPORT_BREACH_PENALTY

            # NOTE: Rev K20 stored_energy_cost was removed - it incorrectly made
            # charging unprofitable by adding cost on discharge without offsetting
            # credit on charge. wear_cost and the SoC target penalty are sufficient
            # for arbitrage decisions.

            slot_ev_cost: float = 0.0  # EV incentive handled in aggregate objective below

            total_cost.append(
                slot_import_cost
                - slot_export_revenue
                + slot_wear_cost
                + slot_ramping_cost
                + slot_curtailment_cost
                + slot_shedding_cost
                + slot_import_breach_cost
                + slot_ev_cost
            )

            # Soft Min/Max SoC Constraints
            prob += soc[t] >= min_soc_kwh - soc_violation[t]
            prob += soc[t] <= max_soc_kwh + soc_overshoot[t]

        # Terminal constraints
        prob += soc[T] >= min_soc_kwh - soc_violation[T]
        prob += soc[T] <= max_soc_kwh + soc_overshoot[T]

        # Terminal SoC Target (BIDIRECTIONAL soft constraint)
        # Penalize both being UNDER target (risk) AND OVER target (missed discharge opportunity)
        target_soc_kwh: float = (
            config.target_soc_kwh if config.target_soc_kwh is not None else min_soc_kwh
        )

        if config.target_soc_kwh is not None:
            # Under target: soc[T] >= target - under_violation
            prob += soc[T] >= target_soc_kwh - target_under_violation

            # Penalize UNDER target (important)
            total_cost.append(target_soc_penalty * target_under_violation)
        else:
            # If no target, we don't care where we end up (within min_soc limits)
            pass

        # EV goal constraints: soft target-by-time requirement and optional
        # per-in-horizon-day quota (multi-day spreading).
        in_horizon_days: set[date] = {slots[t].start_time.date() for t in range(T)}
        ev_shortfall_penalty = getattr(
            config, "ev_shortfall_penalty_sek_per_kwh", EV_SHORTFALL_PENALTY_DEFAULT
        )
        for charger in plugged_chargers:
            d = charger.id
            effective_deadline = charger.deadline or (slots[-1].end_time if slots else None)
            if charger.required_kwh is None or effective_deadline is None:
                continue
            if charger.required_kwh <= 0:
                continue

            surplus_kw_for_charger = ev_surplus_kw.get(d)

            if charger.quota_by_day:
                # One cap per in-horizon day (replaces the old today-only cap).
                for day, quota in charger.quota_by_day.items():
                    if day not in in_horizon_days:
                        continue
                    day_terms = _ev_day_energy_terms(
                        day, d, ev_energy, surplus_kw_for_charger, slots, slot_hours, T
                    )
                    prob += pulp.lpSum(day_terms) <= quota

                # Cap the soft requirement at what's actually allocatable
                # in-horizon, so the shortfall term can't force tomorrow's
                # slots to deliver the whole multi-day requirement.
                effective_required = min(
                    charger.required_kwh,
                    sum(
                        quota
                        for day, quota in charger.quota_by_day.items()
                        if day in in_horizon_days
                    ),
                )
            else:
                effective_required = charger.required_kwh

            # Slots that end on or before the deadline (scheduled energy only —
            # surplus charging is a bonus on top, not counted against the
            # shortfall requirement; it IS counted against the per-day quota
            # above so a spread-out plan can't be blown by a surplus windfall).
            eligible_energy = pulp.lpSum(
                ev_energy[d][t] for t in range(T) if slots[t].end_time <= effective_deadline
            )

            # Soft requirement: delivered + shortfall >= required
            prob += eligible_energy + ev_shortfall[d] >= effective_required
            total_cost.append(ev_shortfall_penalty * ev_shortfall[d])

        # Water Heating Constraints — per-device (tasks 2.4-2.6)
        sorted_days: list[Any] = []  # Initialize to avoid unbound error
        gap_penalty_active: bool = (
            config.water_heating_max_gap_hours > 0 and config.water_gap_penalty_sek > 0
        )
        if water_enabled:
            avg_slot_hours: float = sum(slot_hours) / len(slot_hours) if slot_hours else 0.25

            # Build day → slot indices map (shared across all devices, global deferral)
            slots_by_day: defaultdict[Any, list[int]] = defaultdict(list)
            defer_hours: float = config.defer_up_to_hours
            for t in range(T):
                dt: Any = slots[t].start_time
                bucket_date: Any = dt.date()
                if defer_hours > 0 and dt.hour < defer_hours:
                    bucket_date = bucket_date - timedelta(days=1)
                slots_by_day[bucket_date].append(t)
            sorted_days = sorted(slots_by_day.keys())

            for heater in water_heaters:
                d = heater.id
                # Per-device kWh per slot (power differs between heaters)
                kwh_per_slot: float = heater.power_kw * avg_slot_hours

                # Constraint 1: Per-device, per-day daily minimum (task 2.4)
                for i, day in enumerate(sorted_days):
                    day_slot_indices: list[int] = slots_by_day[day]
                    if i == 0:
                        # First day: deduct per-device heated-today progress
                        day_min_kwh: float = max(
                            0.0, heater.min_kwh_per_day - heater.heated_today_kwh
                        )
                    else:
                        day_min_kwh = heater.min_kwh_per_day

                    if day_min_kwh > 0:
                        prob += (  # type: ignore[operator]
                            pulp.lpSum(water_heat[d][t] for t in day_slot_indices) * kwh_per_slot
                            >= day_min_kwh - water_min_kwh_violation[d][i]
                        )

                # Constraint 2: Per-device soft block breaker (task 2.5)
                if config.water_block_penalty_sek > 0:
                    max_block_slots: int = max(1, int(config.max_block_hours / avg_slot_hours))
                    window_size: int = max_block_slots + 1
                    for t in range(T - window_size + 1):
                        prob += (  # type: ignore[operator]
                            pulp.lpSum(water_heat[d][j] for j in range(t, t + window_size))
                            <= max_block_slots + block_overshoot[d][t]
                        )

                # Constraint 3: Per-device hard spacing constraint (task 2.6)
                if heater.min_spacing_hours > 0 and d in water_start:
                    spacing_slots: int = max(1, int(heater.min_spacing_hours / avg_slot_hours))
                    M: int = spacing_slots
                    for t in range(T):
                        start_idx: int = max(0, t - spacing_slots)
                        prob += (  # type: ignore[operator]
                            pulp.lpSum(water_heat[d][j] for j in range(start_idx, t))
                            + water_start[d][t] * M  # type: ignore[operator]
                            <= M
                        )

                # Constraint 4: Per-device gap-comfort deadband (Decision 1)
                if gap_penalty_active:
                    gap_m: float = 100.0
                    for t in range(T):
                        duration: float = slot_hours[t]
                        if t == 0:
                            prob += (  # type: ignore[operator]
                                discomfort[d][t] >= duration - water_heat[d][t] * gap_m
                            )
                        else:
                            prob += (  # type: ignore[operator]
                                discomfort[d][t]
                                >= discomfort[d][t - 1] + duration - water_heat[d][t] * gap_m
                            )
                        prob += (  # type: ignore[operator]
                            gap_over[d][t] >= discomfort[d][t] - config.water_heating_max_gap_hours
                        )

        # Terminal SoC Target (BIDIRECTIONAL soft constraint)
        # - min_soc violation: HARD penalty (1000 SEK/kWh)
        # - target violation: SOFT penalty (from config, derived from risk_appetite)
        #   * UNDER target: Risk penalty (configurable)
        #   * OVER target: Opportunity cost penalty (same as under)
        # - gap violation: SOFT comfort penalty (Rev K18)
        prob += (  # type: ignore[operator]
            pulp.lpSum(total_cost)
            + MIN_SOC_PENALTY * pulp.lpSum(soc_violation)
            + MAX_SOC_PENALTY * pulp.lpSum(soc_overshoot)
            + (
                EXPORT_FLOOR_PENALTY * pulp.lpSum(export_floor_violation[t] for t in range(T))
                if export_floor_active
                else 0.0
            )
            # Per-device gap-comfort penalty (Decision 1)
            + (
                pulp.lpSum(gap_over[d][t] for d in gap_over for t in range(T))
                * config.water_gap_penalty_sek
                if water_enabled and gap_penalty_active
                else 0.0
            )
            # Per-device block overshoot penalty (task 2.9)
            + (
                pulp.lpSum(block_overshoot[d][t] for d in block_overshoot for t in range(T))
                * config.water_block_penalty_sek
                if water_enabled
                else 0.0
            )
            # Per-device block start penalty (task 2.9)
            + (
                pulp.lpSum(water_start[d][t] for d in water_start for t in range(T))
                * config.water_block_start_penalty_sek
                if water_enabled and water_start and config.water_block_start_penalty_sek > 0
                else 0.0
            )
            # Per-device symmetry breaker (task 2.9)
            + (
                pulp.lpSum(water_heat[d][t] * (t * 1e-5) for d in water_heat for t in range(T))
                if water_enabled
                else 0.0
            )
            # Per-device reliability penalties (task 2.9)
            + (
                pulp.lpSum(
                    water_min_kwh_violation[d][i]
                    for d in water_min_kwh_violation
                    for i in range(len(sorted_days))
                )
                * config.water_reliability_penalty_sek
                if water_enabled
                else 0.0
            )
        )

        # Solve using GLPK (available in Alpine) or CBC as fallback
        import time

        build_start: float = time.time()
        # Solver setup is fast, but let's track the overhead of calling the solver command
        # Note: pulp.LpProblem construction happened above, so 'build_time' here is mostly
        # just the overhead of writing the LP file in prob.solve()

        try:
            # Try GLPK first (installed in Alpine Docker image) with timeout
            solver_cmd: Any = pulp.GLPK_CMD(msg=False, timeLimit=30)
            prob.solve(solver_cmd)  # type: ignore[reportUnknownMemberType]
        except Exception:
            # Fall back to CBC if GLPK not available, also with timeout
            solver_cmd: Any = pulp.PULP_CBC_CMD(msg=False, timeLimit=30)
            prob.solve(solver_cmd)  # type: ignore[reportUnknownMemberType]

        solve_end: float = time.time()

        # Extract Results
        status: str = pulp.LpStatus[prob.status]  # type: ignore[index]
        is_optimal: bool = status == "Optimal"

        # Log Performance Metrics
        solve_duration: float = solve_end - build_start  # This is just the solve() call duration
        # Count stats
        var_count: int = len(prob.variables())  # type: ignore[reportUnknownMemberType,arg-type]
        const_count: int = len(prob.constraints)  # type: ignore[reportUnknownMemberType,arg-type]

        if not is_optimal:
            prob.writeLP("kepler_debug.lp")  # type: ignore[reportUnknownMemberType]
            logger.warning("Solver failed: %s. LP written to kepler_debug.lp", status)

            # Map PuLP status to structured PlannerError
            details = {"solver_status": status, "solve_duration_s": round(solve_duration, 3)}
            if prob.status == pulp.LpStatusInfeasible:  # type: ignore[reportUnknownMemberType,reportAttributeAccessIssue]
                raise PlannerError(code=PlannerErrorCode.SOLVER_INFEASIBLE, details=details)
            elif solve_duration >= 30:  # timeLimit used above
                raise PlannerError(code=PlannerErrorCode.SOLVER_TIMEOUT, details=details)
            elif prob.status == pulp.LpStatusUndefined:  # type: ignore[reportUnknownMemberType,reportAttributeAccessIssue]
                raise PlannerError(code=PlannerErrorCode.SOLVER_UNDEFINED, details=details)

        result_slots: list[KeplerResultSlot] = []
        final_total_cost: float = 0.0

        if is_optimal:
            # Per-charger shortfall vs required_kwh (reported on every slot)
            ev_shortfall_by_charger: dict[str, float] = {}
            for charger in plugged_chargers:
                d = charger.id
                if charger.required_kwh is not None and d in ev_shortfall:
                    shortfall_val: float | None = pulp.value(ev_shortfall[d])  # type: ignore[assignment]
                    ev_shortfall_by_charger[d] = shortfall_val if shortfall_val is not None else 0.0

            for t in range(T):
                s: Any = slots[t]
                h: float = slot_hours[t]

                c_val: float | None = pulp.value(charge[t])  # type: ignore[assignment]
                d_val: float | None = pulp.value(discharge[t])  # type: ignore[assignment]
                i_val: float | None = pulp.value(grid_import[t])  # type: ignore[assignment]
                e_val: float | None = pulp.value(grid_export[t])  # type: ignore[assignment]
                soc_val: float | None = pulp.value(soc[t + 1])  # type: ignore[assignment]

                # Per-device water heating results (task 2.10)
                water_heater_results: dict[str, float] = {}
                total_water_kw: float = 0.0
                water_heating_boost: dict[str, bool] = {}
                if water_enabled:
                    for heater in water_heaters:
                        d_wh = heater.id
                        w_val: float | None = pulp.value(water_heat[d_wh][t])  # type: ignore[assignment]
                        b_val: float | None = (
                            pulp.value(water_boost[d_wh][t])  # type: ignore[assignment]
                            if d_wh in water_boost
                            else None
                        )
                        device_kw: float = (
                            heater.power_kw if w_val is not None and w_val > 0.5 else 0.0
                        )
                        # Boost is active when boost variable is on (even if normal is also on)
                        is_boost: bool = b_val is not None and b_val > 0.5
                        if is_boost:
                            device_kw = heater.power_kw
                            water_heating_boost[d_wh] = True
                        water_heater_results[d_wh] = device_kw
                        total_water_kw += device_kw
                w_kw: float = total_water_kw  # aggregate (backward compat)

                # Per-device EV charging results
                ev_charger_results: dict[str, float] = {}
                total_ev_kw: float = 0.0
                for charger in plugged_chargers:
                    d = charger.id
                    ev_val: float | None = pulp.value(ev_energy[d][t])  # type: ignore[assignment]
                    device_kw: float = ev_val / h if ev_val is not None and h > 0 else 0.0
                    ev_charger_results[d] = device_kw
                    total_ev_kw += device_kw
                ev_kw = total_ev_kw

                # Per-entry custom-entity results, keyed by priority-list rank (task 2.7)
                custom_entity_active_result: dict[str, bool] = {}
                for rank_str, _entry in custom_entity_items:
                    cev_val: float | None = pulp.value(custom_entity_active[rank_str][t])  # type: ignore[assignment]
                    custom_entity_active_result[rank_str] = cev_val is not None and cev_val > 0.5

                # Per-charger EV surplus results (task 2.7)
                ev_surplus_result: dict[str, float] = {}
                for charger_id, _charger, _reward in ev_surplus_items:
                    surplus_val: float | None = pulp.value(ev_surplus_kw[charger_id][t])  # type: ignore[assignment]
                    ev_surplus_result[charger_id] = surplus_val if surplus_val is not None else 0.0

                wear: float = (
                    (c_val + d_val) * config.wear_cost_sek_per_kwh * 0.5
                    if c_val is not None and d_val is not None
                    else 0.0
                )
                effective_export_price_result: float = (
                    s.export_price_sek_kwh - config.export_threshold_sek_per_kwh
                )
                cost: float = (
                    (i_val * s.import_price_sek_kwh)
                    - (e_val * effective_export_price_result)
                    + wear
                    if i_val is not None and e_val is not None
                    else 0.0
                )
                final_total_cost += cost

                result_slots.append(
                    KeplerResultSlot(
                        start_time=s.start_time,
                        end_time=s.end_time,
                        charge_kwh=c_val,  # type: ignore[arg-type]
                        discharge_kwh=d_val,  # type: ignore[arg-type]
                        grid_import_kwh=i_val,  # type: ignore[arg-type]
                        grid_export_kwh=e_val,  # type: ignore[arg-type]
                        soc_kwh=soc_val,  # type: ignore[arg-type]
                        cost_sek=cost,
                        import_price_sek_kwh=s.import_price_sek_kwh,
                        export_price_sek_kwh=s.export_price_sek_kwh,
                        water_heat_kw=w_kw,
                        water_heater_results=water_heater_results,
                        water_heating_boost=water_heating_boost,
                        custom_entity_active=custom_entity_active_result,
                        ev_charge_kw=ev_kw,
                        ev_charger_results=ev_charger_results,
                        ev_surplus_kw=ev_surplus_result,
                        ev_shortfall_kwh=ev_shortfall_by_charger,
                        is_optimal=True,
                    )
                )

            # Update the log with correct cost (since we calculated it in the loop)
            logger_perf = logging.getLogger("darkstar.performance")
            logger_perf.setLevel(logging.INFO)  # Ensure we see it
            logger_perf.info(
                "Kepler Solved: %d slots in %.3fs (Vars: %d, Const: %d) | Cost: %.2f SEK",
                T,
                solve_duration,
                var_count,
                const_count,
                final_total_cost,
            )

        return KeplerResult(
            slots=result_slots,
            total_cost_sek=final_total_cost,
            is_optimal=is_optimal,
            status_msg=status,
        )
