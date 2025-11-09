// ONLY TO BE USED AS A REFERENCE!

// ========================================
// HELIOS CONTROLLER v3.1 - Execute DB Slot Plan
// Purpose: Read slot plan, set SoC target, calculate charge current, output control flags
// Last Updated: 2025-01-21
//
// Changes in v3.1:
// - Fixed initialization order for isHeatingWater
// - Use worst-case voltage (46V) for current calculations
// - Max out current at 190A for >=8kW targets
// - Fixed headroom calculation to not double-count water heater
// ========================================

const CONFIG = {
    battery_capacity_kwh: 27,        // Usable capacity
    system_voltage_V: 48,             // Nominal (but use 46V for worst case)
    worst_case_voltage_V: 46,         // Minimum voltage for current calculations
    min_charge_A: 60,
    max_charge_A: 190,
    round_step_A: 5,
    write_threshold_A: 5,
    inverter_ac_limit_kw: 8.8,
    charge_efficiency: 0.92,
    water_temp_normal: 60,
    water_temp_off: 40,
    min_soc_target: 15
};

// --- INPUT DATA ---
const overrideData = $input.first().json;
const haData = $('Call Gather HA States').first().json;

// Check if override is active
if (overrideData.override_needed && overrideData.override_type !== "none") {
    // Override active - pass through override actions
    return [{
        json: {
            source: "override",
            soc_target: overrideData.actions.soc_target || 10,
            charge_enabled: overrideData.actions.grid_charging || false,
            export_enabled: false,
            water_enabled: overrideData.actions.water_temp ? true : false,
            water_temp: overrideData.actions.water_temp || CONFIG.water_temp_off,
            charge_current_A: 0,
            write_charge_current: false,
            export_current_A: 0,
            write_export_current: false,
            reason: `Override: ${overrideData.reason}`,
            flags: {
                override_active: true,
                override_type: overrideData.override_type
            }
        }
    }];
}

// --- SLOT PLAN (from Override passthrough) ---
const slot = overrideData.slot_plan;

if (!slot || !overrideData.slot_valid) {
    // No valid slot - idle mode
    return [{
        json: {
            source: "fallback_idle",
            soc_target: CONFIG.min_soc_target,
            charge_enabled: false,
            export_enabled: false,
            water_enabled: false,
            water_temp: CONFIG.water_temp_off,
            charge_current_A: 0,
            write_charge_current: false,
            export_current_A: 0,
            write_export_current: false,
            reason: "No valid slot - idle",
            flags: {}
        }
    }];
}

// Parse slot values
const chargeKw = parseFloat(slot.charge_kw) || 0;
const exportKw = parseFloat(slot.export_kw) || 0;
const waterKw = parseFloat(slot.water_kw) || 0;
const socTarget = parseInt(slot.soc_target) || 12;

// --- DETERMINE ACTION (moved up before headroom calculation) ---
const isCharging = chargeKw > 0;
const isExporting = exportKw > 0;
const isHeatingWater = waterKw > 0;

// Current state
const socNow = parseFloat(haData.SoC?.attributes?.['BMS SOC'] || haData.SoC?.state || 50);
const loadPowerW = parseFloat(haData.LoadPower?.state || 0);
const vvbPowerW = parseFloat(haData.VVBPower?.state || 0);
const currentSetA = parseFloat(haData['number.inverter_battery_max_charging_current']?.state || 0);

// Calculate live AC headroom
// Don't double-count water heater if it's part of the plan
const baseLoadKw = loadPowerW / 1000;  // House load only
const waterHeaterKw = isHeatingWater ? waterKw : (vvbPowerW / 1000);  // Planned or observed
const dynamicHeadroomKw = Math.max(0, CONFIG.inverter_ac_limit_kw - baseLoadKw - waterHeaterKw);

// Initialize control variables
let chargeEnabled = false;
let exportEnabled = false;
let waterEnabled = false;
let waterTemp = CONFIG.water_temp_off;
let chargeCurrentA = 0;
let writeChargeCurrent = false;
let exportCurrentA = 0;
let writeExportCurrent = false;
let reason = "";

// PRIORITY 1: Charging
if (isCharging) {
    chargeEnabled = true;

    // Calculate charge current from kW target
    const targetKw = Math.min(chargeKw, dynamicHeadroomKw);

    // If we want max power (>=8kW), just set max current to handle voltage variations
    let requiredA;
    if (targetKw >= 8.0) {
        requiredA = CONFIG.max_charge_A;  // 190A to ensure we get full power
    } else {
        // For lower power, calculate with worst case voltage
        requiredA = (targetKw * 1000) / CONFIG.worst_case_voltage_V;
        requiredA = Math.max(CONFIG.min_charge_A, Math.min(CONFIG.max_charge_A, requiredA));
    }

    // Stop charging if already at target
    if (socNow >= socTarget - 0.5) {
        requiredA = 0;
        chargeEnabled = false;
        reason += "Charge target reached | ";
    }

    chargeCurrentA = Math.round(requiredA / CONFIG.round_step_A) * CONFIG.round_step_A;
    writeChargeCurrent = Math.abs(chargeCurrentA - currentSetA) >= CONFIG.write_threshold_A;

    reason += `Charging: ${chargeKw} kW → ${chargeCurrentA} A (target SoC ${socTarget}%) | `;
}

// PRIORITY 2: Exporting
else if (isExporting) {
    exportEnabled = true;

    // Calculate discharge current from kW target
    const targetKw = Math.min(exportKw, dynamicHeadroomKw);

    // If we want max power (>=8kW), just set max current
    let requiredA;
    if (targetKw >= 8.0) {
        requiredA = CONFIG.max_charge_A;  // 190A for max discharge
    } else {
        // For lower power, calculate with worst case voltage
        // For discharge, inverter efficiency matters (DC must provide more)
        const targetKwDC = targetKw / CONFIG.charge_efficiency;
        requiredA = (targetKwDC * 1000) / CONFIG.worst_case_voltage_V;
        requiredA = Math.max(0, Math.min(CONFIG.max_charge_A, requiredA));
    }

    // Stop exporting if already at floor
    if (socNow <= socTarget + 0.5) {
        requiredA = 0;
        exportEnabled = false;
        reason += "Export floor reached | ";
    }

    exportCurrentA = Math.round(requiredA / CONFIG.round_step_A) * CONFIG.round_step_A;

    // Read current export current setting
    const currentExportSetEntity = haData['number.inverter_battery_max_discharging_current'];
    const currentExportSetA = currentExportSetEntity?.state ? parseFloat(currentExportSetEntity.state) : null;

    // Only write if entity exists and difference is significant
    writeExportCurrent = currentExportSetA !== null &&
    Math.abs(exportCurrentA - currentExportSetA) >= CONFIG.write_threshold_A;

    reason += `Exporting: ${exportKw} kW → ${exportCurrentA} A (floor SoC ${socTarget}%) | `;
}

// PRIORITY 3: Water heating
if (isHeatingWater) {
    waterEnabled = true;
    waterTemp = CONFIG.water_temp_normal;
    reason += `Water heating: ${waterKw} kW | `;
}

// IDLE: No action
if (!isCharging && !isExporting && !isHeatingWater) {
    reason += `Idle (SoC target ${socTarget}%) | `;
}

// --- OUTPUT ---
return [{
    json: {
        source: "controller",
        soc_target: socTarget,
        charge_enabled: chargeEnabled,
        export_enabled: exportEnabled,
        water_enabled: waterEnabled,
        water_temp: waterTemp,
        charge_current_A: chargeCurrentA,
        write_charge_current: writeChargeCurrent,
        export_current_A: exportCurrentA,
        write_export_current: writeExportCurrent,
        reason: reason.trim(),
        flags: {
            is_charging: isCharging,
            is_exporting: isExporting,
            is_heating_water: isHeatingWater,
            slot_number: slot.slot_number,
            slot_start: slot.slot_start
        },
        debug: {
            soc_now: socNow,
            soc_target: socTarget,
            charge_kw: chargeKw,
            export_kw: exportKw,
            water_kw: waterKw,
            headroom_kw: dynamicHeadroomKw.toFixed(2),
            current_set_A: currentSetA,
            target_kw: isCharging ? Math.min(chargeKw, dynamicHeadroomKw) :
            isExporting ? Math.min(exportKw, dynamicHeadroomKw) : 0
        }
    }
}];
