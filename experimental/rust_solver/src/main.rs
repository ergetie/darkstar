use anyhow::{Context, Result};
use chrono::{DateTime, Timelike, Utc};
use good_lp::{highs, variable, Expression, SolverModel, Solution, IntoAffineExpression};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::time::Instant;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct KeplerConfig {
    pub capacity_kwh: f64,
    pub min_soc_percent: f64,
    pub max_soc_percent: f64,
    pub max_charge_power_kw: f64,
    pub max_discharge_power_kw: f64,
    pub charge_efficiency: f64,
    pub discharge_efficiency: f64,
    pub wear_cost_sek_per_kwh: f64,
    pub max_export_power_kw: Option<f64>,
    pub max_import_power_kw: Option<f64>,
    pub target_soc_kwh: Option<f64>,
    pub target_soc_penalty_sek: f64,
    pub terminal_value_sek_kwh: f64,
    pub ramping_cost_sek_per_kw: f64,
    pub export_threshold_sek_per_kwh: f64,
    pub grid_import_limit_kw: Option<f64>,
    pub water_heating_power_kw: f64,
    pub water_heating_min_kwh: f64,
    pub water_heating_max_gap_hours: f64,
    pub water_heated_today_kwh: f64,
    pub water_comfort_penalty_sek: f64,
    pub water_min_spacing_hours: f64,
    pub water_spacing_penalty_sek: f64,
    pub force_water_on_slots: Option<Vec<usize>>,
    pub water_block_start_penalty_sek: f64,
    pub defer_up_to_hours: f64,
    pub enable_export: bool,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct KeplerInputSlot {
    pub start_time: DateTime<Utc>,
    pub end_time: DateTime<Utc>,
    pub load_kwh: f64,
    pub pv_kwh: f64,
    pub import_price_sek_kwh: f64,
    pub export_price_sek_kwh: f64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct KeplerInput {
    pub slots: Vec<KeplerInputSlot>,
    pub initial_soc_kwh: f64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct SidecarInput {
    pub input: KeplerInput,
    pub config: KeplerConfig,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct KeplerResultSlot {
    pub start_time: DateTime<Utc>,
    pub end_time: DateTime<Utc>,
    pub charge_kwh: f64,
    pub discharge_kwh: f64,
    pub grid_import_kwh: f64,
    pub grid_export_kwh: f64,
    pub soc_kwh: f64,
    pub cost_sek: f64,
    pub import_price_sek_kwh: f64,
    pub export_price_sek_kwh: f64,
    pub water_heat_kw: f64,
    pub terminal_credit_sek: f64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct KeplerResult {
    pub slots: Vec<KeplerResultSlot>,
    pub total_cost_sek: f64,
    pub is_optimal: bool,
    pub status_msg: String,
    pub solve_time_ms: f64,
}

fn main() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("Usage: rust-kepler-solver <input_json_path> [output_json_path]");
        std::process::exit(1);
    }

    let input_path = &args[1];
    let output_path = if args.len() > 2 { Some(&args[2]) } else { None };

    let input_text = fs::read_to_string(input_path)
        .with_context(|| format!("Failed to read input file: {}", input_path))?;

    let sidecar_input: SidecarInput = serde_json::from_str(&input_text)
        .with_context(|| "Failed to parse input JSON")?;

    // println!("Loaded KeplerInput with {} slots", sidecar_input.input.slots.len());
    // println!("Config: {:?}", sidecar_input.config);

    let result = solve_kepler(&sidecar_input)?;
    // let total_duration = build_start.elapsed();

    // println!("Solved in {:.3}s (is_optimal: {})", total_duration.as_secs_f64(), result.is_optimal);

    if let Some(out_path) = output_path {
        let result_json = serde_json::to_string_pretty(&result)?;
        fs::write(out_path, result_json)
            .with_context(|| format!("Failed to write output file: {}", out_path))?;
        // println!("Result written to {}", out_path);
    } else {
        println!("Result (stdout summary):");
        println!("  Total Cost: {:.2} SEK", result.total_cost_sek);
        println!("  Status: {}", result.status_msg);
        println!("  Slots: {}", result.slots.len());
    }

    Ok(())
}

fn solve_kepler(sidecar_input: &SidecarInput) -> Result<KeplerResult> {
    let config = &sidecar_input.config;
    let input = &sidecar_input.input;
    let t_total = input.slots.len();

    if t_total == 0 {
        return Ok(KeplerResult {
            slots: Vec::new(),
            total_cost_sek: 0.0,
            is_optimal: true,
            status_msg: "No slots".to_string(),
            solve_time_ms: 0.0,
        });
    }

    let s0 = &input.slots[0];
    let slot_duration_h = (s0.end_time - s0.start_time).num_seconds() as f64 / 3600.0;

    // Hardcoded Penalties (Matching Python kepler.py constants)
    let min_soc_penalty = 1000.0;
    let curtailment_penalty = 0.1;
    let load_shedding_penalty = 10000.0;
    let import_breach_penalty = 5000.0; // from config defaults effectively

    let mut variables = good_lp::variables!();

    let min_soc_kwh = config.min_soc_percent * config.capacity_kwh / 100.0;
    let max_soc_kwh = config.max_soc_percent * config.capacity_kwh / 100.0;
    let max_charge_kwh = config.max_charge_power_kw * slot_duration_h;
    let max_discharge_kwh = config.max_discharge_power_kw * slot_duration_h;

    // Define Variables
    let mut grid_import = Vec::with_capacity(t_total);
    let mut grid_export = Vec::with_capacity(t_total);
    let mut charge = Vec::with_capacity(t_total);
    let mut discharge = Vec::with_capacity(t_total);
    let mut water_heat = Vec::with_capacity(t_total);
    let mut water_start = Vec::with_capacity(t_total);
    let mut soc = Vec::with_capacity(t_total + 1);

    // Slack Variables (Soft Constraints)
    let mut soc_violation = Vec::with_capacity(t_total + 1);
    let mut ramp_up = Vec::with_capacity(t_total);
    let mut ramp_down = Vec::with_capacity(t_total);
    let mut import_breach = Vec::with_capacity(t_total);
    let mut curtailment = Vec::with_capacity(t_total);
    let mut load_shedding = Vec::with_capacity(t_total);

    // Water Gap Slack Variables
    // The Python solver defines dictionary variables, we'll use Option<Vec> to store them if needed
    // Actually we can just create flat vectors and only use indices that make sense
    // but easier to just create them for all if needed, or better:
    // We only need them if features are enabled.
    let mut gap_violation: Vec<good_lp::Variable> = Vec::new();
    let mut gap_violation_2: Vec<good_lp::Variable> = Vec::new();

    let water_enabled = config.water_heating_power_kw > 0.0;

    for _ in 0..t_total {
        grid_import.push(variables.add(variable().min(0.0)));
        grid_export.push(variables.add(variable().min(0.0)));
        charge.push(variables.add(variable().min(0.0).max(max_charge_kwh)));
        discharge.push(variables.add(variable().min(0.0).max(max_discharge_kwh)));

        // Safety Nets
        curtailment.push(variables.add(variable().min(0.0)));
        load_shedding.push(variables.add(variable().min(0.0)));

        // Soft Constraints
        import_breach.push(variables.add(variable().min(0.0)));
        ramp_up.push(variables.add(variable().min(0.0)));
        ramp_down.push(variables.add(variable().min(0.0)));

        if water_enabled {
            water_heat.push(variables.add(variable().binary()));
            water_start.push(variables.add(variable().binary()));

            // Allocate gap vars always to simplify indexing, even if unused?
            // Better to only allocate if needed, but for simplicity let's match T
            if config.water_heating_max_gap_hours > 0.0 {
                 gap_violation.push(variables.add(variable().min(0.0)));
                 gap_violation_2.push(variables.add(variable().min(0.0)));
            }
        }
    }

    for _ in 0..=t_total {
        // SoC variable soft bounds
        // Fix: Use 0.0 and capacity as Hard bounds. Use constraints for Soft min/max.
        soc.push(variables.add(variable().min(0.0).max(config.capacity_kwh)));
        soc_violation.push(variables.add(variable().min(0.0)));
    }

    // Target SoC Slacks
    let target_under_violation = variables.add(variable().min(0.0));
    let target_over_violation = variables.add(variable().min(0.0));

    // Objective function
    let mut objective = Expression::from(0.0);

    // Pre-calculate objective terms using iterators where possible or just standard loop
    // But importantly, ensure we don't clone excessively.
    // The previous loop was fine for objective (N assignments is cheap).

    for t in 0..t_total {
        let slot = &input.slots[t];
        objective += grid_import[t] * slot.import_price_sek_kwh;
        objective -= grid_export[t] * (slot.export_price_sek_kwh - config.export_threshold_sek_per_kwh);
        objective += (charge[t] + discharge[t]) * config.wear_cost_sek_per_kwh;

        objective += curtailment[t] * curtailment_penalty;
        objective += load_shedding[t] * load_shedding_penalty;
        objective += import_breach[t] * import_breach_penalty;

        if config.ramping_cost_sek_per_kw > 0.0 {
             objective += (ramp_up[t] + ramp_down[t]) * (config.ramping_cost_sek_per_kw / slot_duration_h);
        }

        if water_enabled && config.water_block_start_penalty_sek > 0.0 {
            objective += water_start[t] * config.water_block_start_penalty_sek;
        }
    }

    // SoC Violation Penalty
    for t in 0..=t_total {
         objective += soc_violation[t] * min_soc_penalty;
    }

    // Terminal Value
    objective -= soc[t_total] * config.terminal_value_sek_kwh;

    // Target SoC Penalties
    if config.target_soc_kwh.is_some() {
        objective += target_under_violation * config.target_soc_penalty_sek;
        if config.target_soc_kwh.unwrap_or(0.0) > 0.0 {
             objective += target_over_violation * config.target_soc_penalty_sek;
        }
    }

    // Gap Penalties
    if water_enabled && config.water_heating_max_gap_hours > 0.0 && config.water_comfort_penalty_sek > 0.0 {
        for v in &gap_violation {
            objective += *v * config.water_comfort_penalty_sek;
        }
        for v in &gap_violation_2 {
            objective += *v * config.water_comfort_penalty_sek;
        }
    }

    let mut model = variables.minimise(objective.clone()).using(highs);

    // Initial SoC
    model.add_constraint(good_lp::Constraint::from(soc[0].into_expression().eq(input.initial_soc_kwh)));

    for t in 0..t_total {
        let slot = &input.slots[t];
        let water_load_kwh = if water_enabled {
            water_heat[t].into_expression() * config.water_heating_power_kw * slot_duration_h
        } else {
            Expression::from(0.0)
        };

        // 1. Energy Balance (with Safety Nets)
        // load + water + charge + export + curtailment == pv + discharge + import + shading
        let demand = Expression::from(slot.load_kwh) + charge[t] + grid_export[t] + water_load_kwh + curtailment[t];
        let supply = Expression::from(slot.pv_kwh) + discharge[t] + grid_import[t] + load_shedding[t];
        model.add_constraint(good_lp::Constraint::from(demand.eq(supply)));

        // 2. Battery Dynamics
        let eff_d = if config.discharge_efficiency > 0.0 { config.discharge_efficiency } else { 1.0 };
        let next_soc_expr = soc[t].into_expression() + charge[t] * config.charge_efficiency - discharge[t] / eff_d;
        model.add_constraint(good_lp::Constraint::from(soc[t+1].into_expression().eq(next_soc_expr)));

        // Soft Min SoC
        model.add_constraint(good_lp::Constraint::from(soc[t].into_expression().geq(min_soc_kwh - soc_violation[t])));

        // HARD Max SoC (Matching Python implementation)
        // Python: prob += soc[t] <= max_soc_kwh
        model.add_constraint(good_lp::Constraint::from(soc[t].into_expression().leq(max_soc_kwh)));

        // 3. Grid Import Limit (Soft)
        if let Some(limit_kw) = config.grid_import_limit_kw {
            let limit_kwh = limit_kw * slot_duration_h;
            // import <= limit + breach
            model.add_constraint(good_lp::Constraint::from(grid_import[t].into_expression().leq(limit_kwh + import_breach[t])));
        }
        if let Some(limit_kw) = config.max_import_power_kw {
             // Hard limit from config if set? Python treats max_import_power_kw as hard constraint on variable
             // But grid_import_limit_kw is the soft fuse limit.
             // Variable bounds are already set strictly >= 0. We didn't set upper bound on variable definition for import/export
             // Python: prob += grid_import[t] <= config.max_import_power_kw * h
             model.add_constraint(good_lp::Constraint::from(grid_import[t].into_expression().leq(limit_kw * slot_duration_h)));
        }
        if let Some(limit_kw) = config.max_export_power_kw {
             model.add_constraint(good_lp::Constraint::from(grid_export[t].into_expression().leq(limit_kw * slot_duration_h)));
        }

        // 4. Export Toggle
        if !config.enable_export {
            model.add_constraint(good_lp::Constraint::from(grid_export[t].into_expression().eq(0.0)));
        }

        // 5. Ramping Constraints
        // (charge[t] - discharge[t]) - (charge[t-1] - discharge[t-1]) == ramp_up[t] - ramp_down[t]
        if t > 0 {
            let current_net = charge[t].into_expression() - discharge[t];
            let prev_net = charge[t-1].into_expression() - discharge[t-1];
            let ramp_net = ramp_up[t].into_expression() - ramp_down[t];
            model.add_constraint(good_lp::Constraint::from((current_net - prev_net).eq(ramp_net)));
        } else {
             model.add_constraint(good_lp::Constraint::from(ramp_up[t].into_expression().eq(0.0)));
             model.add_constraint(good_lp::Constraint::from(ramp_down[t].into_expression().eq(0.0)));
        }

        // 6. Water Start Logic
        if water_enabled {
            if t == 0 {
                model.add_constraint(good_lp::Constraint::from(water_start[t].into_expression().eq(water_heat[t])));
            } else {
                model.add_constraint(good_lp::Constraint::from(water_start[t].into_expression().geq(water_heat[t].into_expression() - water_heat[t-1])));
            }

            // 7. Force Water On
            if let Some(force_indices) = &config.force_water_on_slots {
                if force_indices.contains(&t) {
                    model.add_constraint(good_lp::Constraint::from(water_heat[t].into_expression().eq(1.0)));
                }
            }
        }
    }

    // Terminal SoC Soft Constraints
    // soc[T] >= min_soc_kwh - soc_violation[T]
    model.add_constraint(good_lp::Constraint::from(soc[t_total].into_expression().geq(min_soc_kwh - soc_violation[t_total])));

    if let Some(target) = config.target_soc_kwh {
        // soc[T] >= target - under
        model.add_constraint(good_lp::Constraint::from(soc[t_total].into_expression().geq(target - target_under_violation)));
        // soc[T] <= target + over
        model.add_constraint(good_lp::Constraint::from(soc[t_total].into_expression().leq(target + target_over_violation)));
    }


    // 8. Water Heating Daily Requirement
    if water_enabled && config.water_heating_min_kwh > 0.0 {
        let mut slots_by_day: BTreeMap<chrono::NaiveDate, Vec<usize>> = BTreeMap::new();
        for (t, slot) in input.slots.iter().enumerate() {
            let mut dt = slot.start_time.naive_utc();
            // Apply deferral offset
            if config.defer_up_to_hours > 0.0 && (dt.hour() as f64) < config.defer_up_to_hours {
                dt = dt - chrono::Duration::days(1);
            }
            slots_by_day.entry(dt.date()).or_default().push(t);
        }

        for (i, (_date, indices)) in slots_by_day.iter().enumerate() {
            let mut day_req = config.water_heating_min_kwh;
            if i == 0 {
                day_req = (day_req - config.water_heated_today_kwh).max(0.0);
            }
            if day_req > 0.0 {
                let day_sum: Expression = indices.iter().map(|&t| water_heat[t]).sum();
                model.add_constraint(good_lp::Constraint::from((day_sum * config.water_heating_power_kw * slot_duration_h).geq(day_req)));
            }
        }
    }

    // 9. Water Comfort Gap (Soft)
    if water_enabled && config.water_heating_max_gap_hours > 0.0 && !gap_violation.is_empty() {
        let gap_slots = (config.water_heating_max_gap_hours / slot_duration_h).max(1.0) as usize;

        // Tier 1
        // for start in range(T - gap_slots + 1):
        //    sum(heat[t]...) + gap_viol[start] >= 1
        if gap_slots <= t_total {
             for start in 0..=(t_total - gap_slots) {
                 // Optimization: Sum slice
                 // But water_heat is Vec<Variable>, we need iterator of Variables
                 // slice range: water_heat[start..start+gap_slots]
                 let sum_h: Expression = water_heat[start..(start + gap_slots)].iter().sum();
                 model.add_constraint(good_lp::Constraint::from((sum_h + gap_violation[start]).geq(1.0)));
             }
        }

        // Tier 2
        let gap_slots_2 = (config.water_heating_max_gap_hours * 1.5 / slot_duration_h).max(1.0) as usize;
        if gap_slots_2 <= t_total {
             for start in 0..=(t_total - gap_slots_2) {
                 let sum_h: Expression = water_heat[start..(start + gap_slots_2)].iter().sum();
                 model.add_constraint(good_lp::Constraint::from((sum_h + gap_violation_2[start]).geq(1.0)));
             }
        }
    }

    // 10. Water Spacing Constraint (Hard)
    // Formulation: If we start a block, we MUST NOT have processed any heating in the previous window.
    if water_enabled && config.water_min_spacing_hours > 0.0 {
        let spacing_slots = (config.water_min_spacing_hours / slot_duration_h).ceil() as usize;
        let m = spacing_slots as f64;
        for t in 1..t_total {
            let start_idx = t.saturating_sub(spacing_slots);
            let preceding_sum: Expression = water_heat[start_idx..t].iter().sum();
            model.add_constraint(good_lp::Constraint::from((preceding_sum + water_start[t] * m).leq(m)));
        }
    }


    let solve_start = Instant::now();
    let solution = model.solve()
        .map_err(|e| anyhow::anyhow!("Solver failed: {:?}. Is optimal: {}", e, false))?;
    let solve_duration_ms = solve_start.elapsed().as_secs_f64() * 1000.0;

    let mut result_slots = Vec::with_capacity(t_total);
    for t in 0..t_total {
        let slot = &input.slots[t];
        let w_kw = if water_enabled {
            if solution.value(water_heat[t]) > 0.5 { config.water_heating_power_kw } else { 0.0 }
        } else {
            0.0
        };

        result_slots.push(KeplerResultSlot {
            start_time: slot.start_time,
            end_time: slot.end_time,
            charge_kwh: solution.value(charge[t]),
            discharge_kwh: solution.value(discharge[t]),
            grid_import_kwh: solution.value(grid_import[t]),
            grid_export_kwh: solution.value(grid_export[t]),
            soc_kwh: solution.value(soc[t+1]),
            cost_sek: (solution.value(grid_import[t]) * slot.import_price_sek_kwh)
                    - (solution.value(grid_export[t]) * slot.export_price_sek_kwh),
            import_price_sek_kwh: slot.import_price_sek_kwh,
            export_price_sek_kwh: slot.export_price_sek_kwh,
            water_heat_kw: w_kw,
            terminal_credit_sek: 0.0,
        });
    }

    Ok(KeplerResult {
        slots: result_slots,
        total_cost_sek: solution.eval(objective),
        is_optimal: true,
        status_msg: "Optimal".to_string(),
        solve_time_ms: solve_duration_ms,
    })
}
