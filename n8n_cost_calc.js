// =============================================================================
// Calculate metrics - v3.2
// =============================================================================
// Purpose: Calculate ACTUAL energy flows using total_increasing sensors
// Last Updated: 2025-01-21
// 
// Changes in v3.2:
// - Added battery cost calculation with weighted average
// - Tracks cost evolution through charge/discharge cycles
// =============================================================================

const CONFIG = {
    battery_capacity_kwh: 27
};

// Get completed slot and planned values
const completed = $('Calculate Completed Slot').first().json;
const planned = $('Read Planned Schedule').first()?.json || {};

// Current sensor readings
const currentReadings = {
    pv: parseFloat($('pv').first().json.state) || 0,
    load: parseFloat($('load').first().json.state) || 0,
    grid_import: parseFloat($('grid_imp').first().json.state) || 0,
    grid_export: parseFloat($('grid_exp').first().json.state) || 0,
    bat_charge: parseFloat($('bat_chg').first().json.state) || 0,
    bat_discharge: parseFloat($('bat_dis').first().json.state) || 0,
    soc: parseFloat($('soc').first().json.state) || 0
};

// Get previous reading from DB (needs a separate SQL node before this)
const previousReadings = $('Get Previous Sensor Readings').first()?.json || {};

// Calculate deltas
let pvKwh = 0, loadKwh = 0, gridImportKwh = 0, gridExportKwh = 0;
let batChargeKwh = 0, batDischargeKwh = 0;

// Check if we have valid previous readings (not first run)
if (previousReadings && previousReadings.pv_total !== undefined && previousReadings.pv_total !== null) {
    // Calculate deltas
    pvKwh = currentReadings.pv - previousReadings.pv_total;
    loadKwh = currentReadings.load - previousReadings.load_total;
    gridImportKwh = currentReadings.grid_import - previousReadings.grid_import_total;
    gridExportKwh = currentReadings.grid_export - previousReadings.grid_export_total;
    batChargeKwh = currentReadings.bat_charge - previousReadings.battery_charge_total;
    batDischargeKwh = currentReadings.bat_discharge - previousReadings.battery_discharge_total;

    // Sanity check - deltas should be positive (sensors are total_increasing)
    pvKwh = Math.max(0, pvKwh);
    loadKwh = Math.max(0, loadKwh);
    gridImportKwh = Math.max(0, gridImportKwh);
    gridExportKwh = Math.max(0, gridExportKwh);
    batChargeKwh = Math.max(0, batChargeKwh);
    batDischargeKwh = Math.max(0, batDischargeKwh);
} else {
    // First run - no previous data, use defaults or skip
    console.log("First run - no previous readings available");
    // Set all deltas to 0 for first run
    pvKwh = 0;
    loadKwh = 0;
    gridImportKwh = 0;
    gridExportKwh = 0;
    batChargeKwh = 0;
    batDischargeKwh = 0;
}

// Convert energy to average power for the period
const actualChargeKw = batChargeKwh * 4;  // kWh in 15 min to kW
const actualDischargeKw = batDischargeKwh * 4;
const actualImportKw = gridImportKwh * 4;
const actualExportKw = gridExportKwh * 4;

// =============================================================================
// SECTION 3: GET PLANNED VALUES & PRICES
// =============================================================================

// Prices (current at time of logging)
const importPrice = parseFloat($('nordpool_import').first().json.import_price) || 0;
const exportPrice = parseFloat($('nordpool_export').first().json.export_price) || 0;

// Planned values from current_schedule
const plannedChargeKw = parseFloat(planned.charge_kw || 0);
const plannedExportKw = parseFloat(planned.export_kw || 0);
const plannedSocProjected = parseFloat(planned.soc_projected || 0);
const plannedLoadKwh = parseFloat(planned.planned_load_kwh || 0);
const plannedPvKwh = parseFloat(planned.planned_pv_kwh || 0);

// =============================================================================
// SECTION 4: CALCULATE COSTS & PROFIT
// =============================================================================

// Actual costs/revenue based on actual flows
const gridChargeCostSek = gridImportKwh * importPrice;
const exportRevenueSek = gridExportKwh * exportPrice;

// Battery energy state (current energy stored)
const batteryEnergyKwh = (currentReadings.soc / 100) * CONFIG.battery_capacity_kwh;

// Profit calculation
const profit = exportRevenueSek - gridChargeCostSek;

// =============================================================================
// SECTION 5: CALCULATE BATTERY COST (WEIGHTED AVERAGE)
// =============================================================================

// Get last known battery cost from previous execution (needs separate SQL query)
const previousBatteryCost = parseFloat($('Get Previous Battery Cost')?.first()?.json?.battery_avg_cost_per_kwh) || 0.85;
const previousBatteryKwh = parseFloat($('Get Previous Battery Cost')?.first()?.json?.battery_energy_kwh) || batteryEnergyKwh;

let newBatteryCost = previousBatteryCost;

// If we charged from grid, update weighted average
if (batChargeKwh > 0 && gridImportKwh > 0) {
    const oldTotalCost = previousBatteryKwh * previousBatteryCost;
    const newEnergyCost = batChargeKwh * importPrice;
    const newTotalKwh = previousBatteryKwh + batChargeKwh;
    const newTotalCost = oldTotalCost + newEnergyCost;

    newBatteryCost = newTotalCost / newTotalKwh;
}

// If we charged from PV (free), dilute the cost
if (pvKwh > loadKwh) {
    const pvSurplus = (pvKwh - loadKwh) * 0.95; // 95% efficiency
    if (pvSurplus > 0) {
        const oldTotalCost = previousBatteryKwh * previousBatteryCost;
        const newTotalKwh = previousBatteryKwh + pvSurplus;
        // Total cost stays same, but kWh increases, so cost/kWh decreases
        newBatteryCost = oldTotalCost / newTotalKwh;
    }
}

// =============================================================================
// OUTPUT
// =============================================================================

return [{
    json: {
        slot_start: completed.slot_start,

        // Planned values
        planned_charge_kw: plannedChargeKw,
        planned_export_kw: plannedExportKw,
        planned_soc_projected: plannedSocProjected,
        planned_load_kwh: plannedLoadKwh,
        planned_pv_kwh: plannedPvKwh,

        // ACTUAL values (from sensor deltas)
        actual_charge_kw: parseFloat(actualChargeKw.toFixed(2)),
        actual_export_kw: parseFloat(actualExportKw.toFixed(2)),
        actual_discharge_kw: parseFloat(actualDischargeKw.toFixed(2)),
        actual_import_kw: parseFloat(actualImportKw.toFixed(2)),
        actual_soc: Math.round(currentReadings.soc),
        actual_load_kwh: parseFloat(loadKwh.toFixed(3)),
        actual_pv_kwh: parseFloat(pvKwh.toFixed(3)),

        // Raw energy deltas
        grid_import_kwh: parseFloat(gridImportKwh.toFixed(3)),
        grid_export_kwh: parseFloat(gridExportKwh.toFixed(3)),
        battery_charge_kwh: parseFloat(batChargeKwh.toFixed(3)),
        battery_discharge_kwh: parseFloat(batDischargeKwh.toFixed(3)),

        // Prices
        import_price: parseFloat(importPrice.toFixed(4)),
        export_price: parseFloat(exportPrice.toFixed(4)),

        // Economics
        profit_sek: parseFloat(profit.toFixed(3)),
        grid_charge_cost_sek: parseFloat(gridChargeCostSek.toFixed(2)),
        battery_energy_kwh: parseFloat(batteryEnergyKwh.toFixed(2)),
        battery_avg_cost_per_kwh: parseFloat(newBatteryCost.toFixed(3)),

        // Debug info
        debug: {
            has_previous: !!previousReadings.timestamp,
            time_since_last: previousReadings.timestamp ?
                ((new Date() - new Date(previousReadings.timestamp)) / 60000).toFixed(1) + ' min' : 'first run',
            current_totals: {
                pv: currentReadings.pv,
                load: currentReadings.load,
                grid_import: currentReadings.grid_import,
                grid_export: currentReadings.grid_export
            },
            battery_cost_calc: {
                previous_cost: previousBatteryCost,
                previous_kwh: previousBatteryKwh,
                grid_charge_kwh: batChargeKwh,
                import_price: importPrice,
                new_cost: newBatteryCost
            }
        }
    }
}];