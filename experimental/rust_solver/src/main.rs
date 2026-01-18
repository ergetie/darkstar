use anyhow::{Context, Result};
use chrono::{DateTime, Datelike, Timelike, Utc};
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

    println!("Loaded KeplerInput with {} slots", sidecar_input.input.slots.len());

    let build_start = Instant::now();
    let result = solve_kepler(&sidecar_input)?;
    let total_duration = build_start.elapsed();

    println!("Solved in {:.3}s (is_optimal: {})", total_duration.as_secs_f64(), result.is_optimal);

    if let Some(out_path) = output_path {
        let result_json = serde_json::to_string_pretty(&result)?;
        fs::write(out_path, result_json)
            .with_context(|| format!("Failed to write output file: {}", out_path))?;
        println!("Result written to {}", out_path);
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

    let water_enabled = config.water_heating_power_kw > 0.0;

    for _ in 0..t_total {
        grid_import.push(variables.add(variable().min(0.0)));
        grid_export.push(variables.add(variable().min(0.0)));
        charge.push(variables.add(variable().min(0.0).max(max_charge_kwh)));
        discharge.push(variables.add(variable().min(0.0).max(max_discharge_kwh)));
        if water_enabled {
            water_heat.push(variables.add(variable().binary()));
            water_start.push(variables.add(variable().binary()));
        }
    }

    for _ in 0..=t_total {
        soc.push(variables.add(variable().min(min_soc_kwh).max(max_soc_kwh)));
    }

    // Objective function
    let mut objective = Expression::from(0.0);
    for t in 0..t_total {
        let slot = &input.slots[t];
        objective = objective + (grid_import[t] * slot.import_price_sek_kwh);
        objective = objective - (grid_export[t] * (slot.export_price_sek_kwh - config.export_threshold_sek_per_kwh));
        objective = objective + ((charge[t] + discharge[t]) * config.wear_cost_sek_per_kwh);

        if water_enabled && config.water_block_start_penalty_sek > 0.0 {
            objective = objective + (water_start[t] * config.water_block_start_penalty_sek);
        }
    }

    objective = objective - (soc[t_total] * config.terminal_value_sek_kwh);

    let mut model = variables.minimise(objective.clone()).using(highs);

    model.add_constraint(good_lp::Constraint::from(soc[0].into_expression().eq(input.initial_soc_kwh)));

    for t in 0..t_total {
        let slot = &input.slots[t];
        let water_load_kwh = if water_enabled {
            water_heat[t].into_expression() * config.water_heating_power_kw * slot_duration_h
        } else {
            Expression::from(0.0)
        };

        // 1. Energy Balance (with water load)
        model.add_constraint(good_lp::Constraint::from((slot.pv_kwh + discharge[t] + grid_import[t]).eq(slot.load_kwh + charge[t] + grid_export[t] + water_load_kwh)));

        // 2. Battery Dynamics
        let eff_d = if config.discharge_efficiency > 0.0 { config.discharge_efficiency } else { 1.0 };
        let next_soc_expr = soc[t].into_expression() + charge[t] * config.charge_efficiency - discharge[t] / eff_d;
        model.add_constraint(good_lp::Constraint::from(soc[t+1].into_expression().eq(next_soc_expr)));

        // 3. Export Toggle
        if !config.enable_export {
            model.add_constraint(good_lp::Constraint::from(grid_export[t].into_expression().eq(0.0)));
        }

        // 4. Water Start Logic
        if water_enabled {
            if t == 0 {
                model.add_constraint(good_lp::Constraint::from(water_start[t].into_expression().eq(water_heat[t])));
            } else {
                model.add_constraint(good_lp::Constraint::from(water_start[t].into_expression().geq(water_heat[t].into_expression() - water_heat[t-1])));
            }

            // 5. Force Water On
            if let Some(force_indices) = &config.force_water_on_slots {
                if force_indices.contains(&t) {
                    model.add_constraint(good_lp::Constraint::from(water_heat[t].into_expression().eq(1.0)));
                }
            }
        }
    }

    // 6. Water Heating Daily Requirement
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
                let mut day_sum = Expression::from(0.0);
                for &t in indices {
                    day_sum = day_sum + water_heat[t];
                }
                model.add_constraint(good_lp::Constraint::from((day_sum * config.water_heating_power_kw * slot_duration_h).geq(day_req)));
            }
        }
    }

    // 7. Water Spacing Constraint (The Combinatorial Bottleneck)
    if water_enabled && config.water_min_spacing_hours > 0.0 {
        let spacing_slots = (config.water_min_spacing_hours / slot_duration_h).ceil() as usize;
        let m = spacing_slots as f64;
        for t in 1..t_total {
            let start_idx = t.saturating_sub(spacing_slots);
            let mut preceding_sum = Expression::from(0.0);
            for j in start_idx..t {
                preceding_sum = preceding_sum + water_heat[j];
            }
            // sum(heat[t-S:t]) + start[t] * S <= S
            model.add_constraint(good_lp::Constraint::from((preceding_sum + water_start[t] * m).leq(m)));
        }
    }

    if let Some(target) = config.target_soc_kwh {
        model.add_constraint(good_lp::Constraint::from(soc[t_total].into_expression().geq(target)));
    }

    let solve_start = Instant::now();
    let solution = model.solve()
        .map_err(|e| anyhow::anyhow!("Solver failed: {:?}", e))?;
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
