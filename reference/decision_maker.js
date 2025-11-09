// THIS IS THE OLD CODE IN JAVASCRIPT, ONLY TO BE USED AS A LOGIC REFERENCE!!!


// =============================================================================
// DECISION MAKER - v6.3 (MPC with Integrated Water Heating) - FIXED
// =============================================================================
// Purpose: Multi-pass Model Predictive Control with strategic charging and integrated water heating
// Last Updated: 2025-01-23
//
// Changes in v6.3:
// - Integrated water heating scheduling (removed separate node)
// - Water heating uses PV > Battery (if economical) > Grid priority
// - Battery threshold: only use if battery_cost + 0.20 < grid_price
// - Proper SoC projection including water heating consumption
// - Fixed cascading inheritance (checks next window capability always)
// - Fixed water heating scheduling (only future slots, checks cumulative kWh)
// - Fixed simulation (doesn't artificially drain battery for water)
// - Fixed average load calculation (uses actual slot data)
//
// Algorithm Overview:
// 1. Detect strategic period (PV < Load = low solar alternative)
// 2. Schedule water heating in cheapest future slots (if not already heated 2+ kWh today)
// 3. Identify cheap windows from Percentile Calculator + strategic threshold
// 4. Simulate battery depletion (NO artificial water drain)
// 5. Calculate cascading responsibilities with fixed inheritance logic
// 6. Iterative SoC-target charging (add slots until target reached)
// 7. Execute schedule with dynamic water heating source selection
// =============================================================================

// =============================================================================
// SECTION 1: INPUT PROCESSING
// =============================================================================

const config = $('Config').first().json;
const deficitData = $('Deficit Analyzer').first().json;
const arbitrageData = $('Arbitrage Identifier').first().json;

// Get battery cost from execution history
const batteryCost = parseFloat($('Get Battery Cost').first().json.battery_avg_cost_per_kwh) || 0.85;

// Get current SoC and daily water heating status
const currentSoC = parseFloat($('current_soc').first().json.state);
const dailyWaterKwh = parseFloat($('daily_water').first().json.state) || 0;
const waterMinimumKwh = config.water_heating.daily_minimum_kwh || 2.0;
const dailyWaterHeated = dailyWaterKwh >= waterMinimumKwh;

const slots = deficitData.slots;
const sIndex = $('S-Index Calculator').first().json.security_index.security_factor;

// Battery parameters
const batteryCapacity = config.battery.usable_kwh;
const maxChargeKw = config.battery.max_charge_kw;
const maxDischargeKw = config.battery.max_discharge_kw;
const socMin = config.battery.soc_min_pct;
const socMax = config.battery.soc_max_pct;
const efficiency = config.battery.roundtrip_efficiency;
const inverterLimit = config.inverter.ac_limit_kw;

// Water heating parameters
const waterHeatingHours = config.water_heating.daily_hours;
const waterPowerKw = config.water_heating.power_kw;
const waterSlotsNeeded = waterHeatingHours * 4; // 2h = 8 slots

// Decision thresholds
const batteryUseMargin = config.decision_thresholds.battery_use_margin_sek || 0.10;
const batteryWaterMargin = config.decision_thresholds.battery_water_margin_sek || 0.20;
const cheapPercentileThreshold = config.percentiles?.charge_threshold || 20;

// Strategic opportunity thresholds
const strategicPriceThreshold = config.decision_thresholds.strategic_price_threshold || 0.90;
const strategicTargetSoC = config.decision_thresholds.strategic_target_soc || 80;

// =============================================================================
// SECTION 1.5: STRATEGIC OPPORTUNITY DETECTION
// =============================================================================

// Calculate if we're in strategic opportunity period
const next24hSlots = slots.slice(0, Math.min(96, slots.length));
const pvForecast24h = next24hSlots.reduce((sum, slot) => sum + (slot.adjusted_pv_kwh || 0), 0);
const avgLoad24h = next24hSlots.reduce((sum, slot) => sum + (slot.adjusted_load_kwh || 0), 0);

// Strategic period = PV can't cover load (no solar alternative)
const isStrategicPeriod = pvForecast24h < avgLoad24h;

// =============================================================================
// SECTION 2: PASS 1 - IDENTIFY CHEAP WINDOWS
// =============================================================================

// SECTION 2.1: Extract cheap slots from Percentile Calculator
const cheapSlots = new Set();
slots.forEach((slot, index) => {
  if (slot.price_category === 'cheap' || slot.import_percentile <= cheapPercentileThreshold) {
    cheapSlots.add(index);
  }
});

// SECTION 2.2: Group consecutive cheap slots into windows
function identifyCheapWindows() {
  const windows = [];
  let currentWindow = null;

  slots.forEach((slot, index) => {
    const isCheap = cheapSlots.has(index);
    const isStrategic = isStrategicPeriod && slot.import_price < strategicPriceThreshold;

    if (isCheap || isStrategic) {
      if (!currentWindow) {
        currentWindow = {
          index: windows.length,
          startSlot: index,
          endSlot: index,
          slots: [index],
          prices: [slot.import_price],
          isStrategic: isStrategic
        };
      } else {
        currentWindow.endSlot = index;
        currentWindow.slots.push(index);
        currentWindow.prices.push(slot.import_price);

        // If ANY slot in window is strategic, mark entire window
        if (isStrategic) {
          currentWindow.isStrategic = true;
        }
      }
    } else {
      if (currentWindow) {
        windows.push(finalizeWindow(currentWindow));
        currentWindow = null;
      }
    }
  });

  if (currentWindow) {
    windows.push(finalizeWindow(currentWindow));
  }

  return windows;
}

// SECTION 2.3: Store window metadata
function finalizeWindow(window) {
  const sortedPrices = [...window.prices].sort((a, b) => a - b);
  return {
    ...window,
    duration: window.slots.length * 0.25,
    startTime: slots[window.startSlot].slot_start,
    endTime: slots[window.endSlot].slot_start,
    minPrice: sortedPrices[0],
    maxPrice: sortedPrices[sortedPrices.length - 1],
    avgPrice: window.prices.reduce((a, b) => a + b, 0) / window.prices.length,

    // Theoretical charging capacity
    theoreticalCapacity: window.slots.length * maxChargeKw * 0.25 * Math.sqrt(efficiency)
  };
}

const cheapWindows = identifyCheapWindows();

// =============================================================================
// SECTION 2.5: SCHEDULE WATER HEATING
// =============================================================================

/**
 * Find optimal slots for water heating
 * Only schedules in FUTURE slots (index > 0)
 * Checks cumulative daily kWh to avoid double-heating
 */
function scheduleWaterHeating() {
  const schedule = {
    slots: [],
    total_hours: 0,
    total_cost_sek: 0,
    strategy: 'none',
    skipped_reason: null
  };

  // Check if planning horizon includes tomorrow (slots after midnight)
  const todayDate = $now.toFormat('yyyy-MM-dd');
  const hasTomorrowSlots = slots.some(slot => {
    const slotDate = slot.slot_start.substring(0, 10);
    return slotDate > todayDate;
  });

  // Only skip scheduling if:
  // 1. Today is already heated AND
  // 2. We don't have tomorrow's slots (no future days to schedule)
  if (dailyWaterHeated && !hasTomorrowSlots) {
    schedule.skipped_reason = `Already heated ${dailyWaterKwh.toFixed(1)} kWh today (minimum: ${waterMinimumKwh} kWh), no tomorrow slots available`;
    return schedule;
  }

  // If today is done but we have tomorrow slots, schedule for tomorrow
  if (dailyWaterHeated && hasTomorrowSlots) {
    schedule.skipped_reason = `Today heated (${dailyWaterKwh.toFixed(1)} kWh), scheduling for tomorrow`;
    // Continue to scheduling logic below
  }

  // Build candidate slots - ONLY FUTURE SLOTS (index > 0)
  // If today is already heated, only consider tomorrow's slots
  const candidates = slots
    .map((slot, index) => {
      // Skip current slot (index 0) - it's too late to schedule
      if (index === 0) return null;

      // If today is already heated, skip today's remaining slots (only schedule tomorrow)
      if (dailyWaterHeated) {
        const slotDate = slot.slot_start.substring(0, 10);
        if (slotDate === todayDate) return null; // Skip today's slots
      }

      const gridCost = slot.import_price * (waterPowerKw * 0.25);
      const batteryCost_calc = batteryCost * (waterPowerKw * 0.25);
      const batteryThreshold = batteryCost + batteryWaterMargin;

      // Decide source: use battery only if significantly cheaper than grid
      const useBattery = slot.import_price > batteryThreshold;
      const cost = useBattery ? batteryCost_calc : gridCost;

      return {
        slot: index,
        time: slot.slot_start,
        grid_price: slot.import_price,
        cost: cost,
        source: useBattery ? 'battery' : 'grid',
        savings: useBattery ? (gridCost - batteryCost_calc) : 0
      };
    })
    .filter(c => c !== null); // Remove null (slot 0)

  // Sort by cost and take cheapest N slots
  candidates.sort((a, b) => a.cost - b.cost);
  const selected = candidates.slice(0, waterSlotsNeeded);

  schedule.slots = selected.map(s => s.slot).sort((a, b) => a - b);
  schedule.total_hours = schedule.slots.length * 0.25;
  schedule.total_cost_sek = selected.reduce((sum, s) => sum + s.cost, 0);

  const batterySlots = selected.filter(s => s.source === 'battery').length;
  const gridSlots = selected.filter(s => s.source === 'grid').length;
  schedule.strategy = `${waterSlotsNeeded} cheapest future slots (Battery: ${batterySlots}, Grid: ${gridSlots})`;

  return schedule;
}

const waterSchedule = scheduleWaterHeating();
const waterHeatingSlots = new Set(waterSchedule.slots);

// =============================================================================
// SECTION 3: PASS 2 - SIMULATE BATTERY DEPLETION
// =============================================================================

// SECTION 3.1: Simulate no-charging scenario
// This shows what happens if we don't charge - tracks battery evolution
function simulateBatteryDepletion() {
  let simKwh = (currentSoC / 100) * batteryCapacity;
  let simSoC = currentSoC;
  const depletionPath = [];
  const windowStates = new Map();

  slots.forEach((slot, index) => {
    // SECTION 3.2: Track battery state at each slot
    const slotState = {
      slot: index,
      time: slot.slot_start,
      kwh_before: simKwh,
      soc_before: simSoC
    };

    // SECTION 3.3: Record state at each window start
    const windowAtThisSlot = cheapWindows.find(w => w.startSlot === index);
    if (windowAtThisSlot) {
      windowStates.set(windowAtThisSlot.index, {
        windowIndex: windowAtThisSlot.index,
        slot: index,
        time: slot.slot_start,
        kwh: simKwh,
        soc: simSoC,
        available: Math.max(0, simKwh - (socMin / 100 * batteryCapacity))
      });
    }

    // Simulate discharge if battery would be used
    if (slot.adjusted_load_kwh > slot.adjusted_pv_kwh) {
      const netLoad = slot.adjusted_load_kwh - slot.adjusted_pv_kwh;

      if (slot.import_price > batteryCost + batteryUseMargin) {
        const batteryAvailable = simKwh - (socMin / 100 * batteryCapacity);
        const useFromBattery = Math.min(batteryAvailable, netLoad);

        if (useFromBattery > 0) {
          simKwh -= useFromBattery / Math.sqrt(efficiency);
          simSoC = (simKwh / batteryCapacity) * 100;
        }
      }
    }

    // Simulate PV surplus charging
    else if (slot.adjusted_pv_kwh > slot.adjusted_load_kwh) {
      const surplus = slot.adjusted_pv_kwh - slot.adjusted_load_kwh;
      const batterySpace = (socMax / 100 * batteryCapacity) - simKwh;
      const chargeFromPV = Math.min(surplus, batterySpace);

      if (chargeFromPV > 0) {
        simKwh += chargeFromPV * Math.sqrt(efficiency);
        simSoC = (simKwh / batteryCapacity) * 100;
      }
    }

    // Enforce limits
    simKwh = Math.max((socMin/100) * batteryCapacity, Math.min((socMax/100) * batteryCapacity, simKwh));
    simSoC = (simKwh / batteryCapacity) * 100;

    slotState.kwh_after = simKwh;
    slotState.soc_after = simSoC;
    slotState.change = simKwh - slotState.kwh_before;

    depletionPath.push(slotState);
  });

  return { depletionPath, windowStates };
}

const simulation = simulateBatteryDepletion();
const windowStates = simulation.windowStates;

// =============================================================================
// SECTION 4: PASS 3 - CALCULATE CASCADING RESPONSIBILITIES
// =============================================================================

// SECTION 4.1: Gap calculation with dynamic battery cost threshold
function calculateGapEnergyWithThreshold(startSlot, endSlot, batteryCostForGap) {
  let energyNeeded = 0;
  const gapSlots = [];
  const threshold = batteryCostForGap + batteryUseMargin;

  for (let i = startSlot; i < endSlot && i < slots.length; i++) {
    const slot = slots[i];

    // Only count slots where battery would actually be used with THIS battery cost
    if (slot.import_price > threshold) {
      const netLoad = Math.max(0, slot.adjusted_load_kwh - slot.adjusted_pv_kwh);
      energyNeeded += netLoad;

      gapSlots.push({
        slot: i,
        time: slot.slot_start,
        price: slot.import_price,
        need: netLoad,
        threshold: threshold
      });
    }
  }

  // Apply security index
  const energyNeededWithSafety = energyNeeded * sIndex;

  return {
    startSlot: startSlot,
    endSlot: endSlot,
    duration: (endSlot - startSlot) * 0.25,
    energyNeeded: energyNeededWithSafety,
    energyNeededRaw: energyNeeded,
    gapSlots: gapSlots,
    threshold: threshold,
    batteryCostUsed: batteryCostForGap
  };
}

// SECTION 4.2: Allocate gaps with dynamic battery cost tracking
function allocateGapsToWindows() {
  const allocations = [];

  // Start with initial battery state and cost
  let trackedKwh = windowStates.get(0) ? windowStates.get(0).kwh : (currentSoC / 100) * batteryCapacity;
  let trackedAvailable = Math.max(0, trackedKwh - (socMin / 100 * batteryCapacity));
  let trackedBatteryCost = batteryCost; // Initial cost from history
  let trackedTotalCost = trackedKwh * batteryCost;

  for (let windowIndex = 0; windowIndex < cheapWindows.length; windowIndex++) {
    const window = cheapWindows[windowIndex];
    const nextWindow = cheapWindows[windowIndex + 1];

    // SECTION 4.2.1: Pre-calculate minimum possible battery cost for this window
    const batterySpaceAvailable = (socMax / 100 * batteryCapacity) - trackedKwh;
    const maxPossibleCharge = Math.min(batterySpaceAvailable, window.theoreticalCapacity / Math.sqrt(efficiency));

    let projectedCostForGaps = trackedBatteryCost;

    if (maxPossibleCharge > 0.1) {
      // Calculate cost if we charge at minimum price (most optimistic scenario)
      const projectedTotalCostMin = trackedTotalCost + (maxPossibleCharge * window.minPrice);
      const projectedKwhMin = trackedKwh + maxPossibleCharge;
      projectedCostForGaps = projectedKwhMin > 0 ? projectedTotalCostMin / projectedKwhMin : trackedBatteryCost;
    }

    const allocation = {
      windowIndex: windowIndex,
      window: window,
      batteryStateAtStart: {
        kwh: trackedKwh,
        available: trackedAvailable,
        soc: (trackedKwh / batteryCapacity) * 100,
        cost: trackedBatteryCost
      },
      allocatedGaps: [],
      totalResponsibility: 0,
      chargingFor: []
    };

    // SECTION 4.3: Calculate immediate gap with projected battery cost
    const gapStartSlot = window.endSlot + 1;
    const gapEndSlot = nextWindow ? nextWindow.startSlot : Math.min(window.endSlot + 96, slots.length);

    let immediateGap = null;

    if (gapStartSlot < gapEndSlot) {
      immediateGap = calculateGapEnergyWithThreshold(gapStartSlot, gapEndSlot, projectedCostForGaps);

      if (immediateGap.energyNeeded > 0) {
        immediateGap.gapIndex = windowIndex;
        immediateGap.afterWindow = windowIndex;
        allocation.allocatedGaps.push(immediateGap);
        allocation.totalResponsibility += immediateGap.energyNeeded;
        allocation.chargingFor.push(`Gap ${windowIndex + 1} (immediate, threshold ${immediateGap.threshold.toFixed(3)})`);
      }
    }

    // SECTION 4.4: Check if we need to inherit future gaps (FIXED - use simulation!)
    if (nextWindow) {
      // Use SIMULATED battery state at next window (realistic, accounts for no charging)
      const nextWindowState = windowStates.get(windowIndex + 1);
      const batteryAtNextWindow = nextWindowState ? nextWindowState.kwh : (socMin / 100 * batteryCapacity);
      const usableAtNextWindow = Math.max(0, batteryAtNextWindow - (socMin / 100 * batteryCapacity)) * Math.sqrt(efficiency);

      // Check next gap regardless of whether immediate gap exists
      const windowAfterNext = cheapWindows[windowIndex + 2];
      const nextGapStart = nextWindow.endSlot + 1;
      const nextGapEnd = windowAfterNext ? windowAfterNext.startSlot : Math.min(nextWindow.endSlot + 96, slots.length);

      if (nextGapStart < nextGapEnd) {
        const nextGap = calculateGapEnergyWithThreshold(nextGapStart, nextGapEnd, projectedCostForGaps);

        if (nextGap.energyNeeded > 0) {
          nextGap.gapIndex = windowIndex + 1;
          nextGap.afterWindow = windowIndex + 1;

          const nextWindowCapacity = nextWindow.theoreticalCapacity;
          const nextWindowDeficit = Math.max(0, nextGap.energyNeeded - usableAtNextWindow);

          // SECTION 4.5: Inherit if next window insufficient
          if (nextWindowCapacity < nextWindowDeficit * 1.1) {
            allocation.allocatedGaps.push(nextGap);
            allocation.totalResponsibility += nextGap.energyNeeded;
            allocation.chargingFor.push(`Gap ${windowIndex + 2} (next insufficient: ${nextWindowCapacity.toFixed(1)} < ${nextWindowDeficit.toFixed(1)}, threshold ${nextGap.threshold.toFixed(3)})`);
          }
        }
      }
    }

    // SECTION 4.6: Strategic override if applicable
    let isAbsoluteTarget = false;

    if (allocation.window.isStrategic || allocation.window.strategicCarryForward) {
      const targetKwh = (batteryCapacity * strategicTargetSoC / 100);
      const chargeToTarget = Math.max(0, targetKwh - allocation.batteryStateAtStart.kwh);

      // Use whichever is larger: gap needs or strategic target
      if (chargeToTarget > allocation.totalResponsibility / Math.sqrt(efficiency)) {
        const strategicReason = `Strategic reserve to ${strategicTargetSoC}% (PV ${pvForecast24h.toFixed(1)} < Load ${avgLoad24h.toFixed(1)}, price ${allocation.window.minPrice.toFixed(2)})`;
        allocation.chargingFor.push(strategicReason);
        allocation.totalResponsibility = chargeToTarget * Math.sqrt(efficiency);
        isAbsoluteTarget = true;
      }
    }

    // Store the flag in allocation object for later use
    allocation.isAbsoluteTarget = isAbsoluteTarget;

    // SECTION 4.7: Calculate actual charging needed
    let actualDeficit;

    if (isAbsoluteTarget) {
      // Strategic target: charge to absolute SoC (don't offset by available)
      const targetKwh = (batteryCapacity * strategicTargetSoC / 100);
      actualDeficit = Math.max(0, targetKwh - allocation.batteryStateAtStart.kwh);
    } else {
      // Gap-based: energy needed minus what we already have available
      const usableAvailable = trackedAvailable * Math.sqrt(efficiency);
      actualDeficit = Math.max(0, allocation.totalResponsibility - usableAvailable);

      // CRITICAL FIX: Add window self-depletion to charging requirement
      // During cheap windows, battery may discharge for load coverage
      // We need to charge enough to compensate for this PLUS cover the gaps
      const windowEndState = windowStates.get(windowIndex + 1);
      if (windowEndState) {
        const depletionDuringWindow = allocation.batteryStateAtStart.kwh - windowEndState.kwh;
        if (depletionDuringWindow > 0) {
          // Battery will deplete during this window, add to charging requirement
          actualDeficit += depletionDuringWindow * Math.sqrt(efficiency);
        }
      }
    }

    allocation.actualDeficit = actualDeficit;
    allocation.chargeNeeded = actualDeficit / Math.sqrt(efficiency);

    // SECTION 4.8: Update tracked state with REALISTIC charging estimate
    // Account for water heating and load constraints when estimating actual charge

    if (allocation.chargeNeeded > 0) {
      // Estimate average available power per slot in this window
      let avgAvailablePower = inverterLimit;

      // Count water heating slots in this window
      const waterSlotsInWindow = window.slots.filter(s => waterHeatingSlots.has(s)).length;
      const waterReduction = waterSlotsInWindow > 0 ?
        (waterPowerKw * waterSlotsInWindow / window.slots.length) :
        (waterPowerKw * 0.4); // Conservative estimate if none scheduled in window

      avgAvailablePower -= waterReduction;

      // Calculate average load from actual slot data in this window
      const avgLoadInWindow = window.slots.reduce((sum, slotIdx) =>
        sum + Math.max(0, slots[slotIdx].adjusted_load_kwh - slots[slotIdx].adjusted_pv_kwh), 0
      ) / window.slots.length;
      const avgLoadKw = avgLoadInWindow * 4; // Convert kWh to kW
      avgAvailablePower -= avgLoadKw;

      // Realistic charge rate
      const realisticChargeKw = Math.min(maxChargeKw, Math.max(0, avgAvailablePower));
      const realisticCapacity = window.slots.length * realisticChargeKw * 0.25 * Math.sqrt(efficiency);

      // Actually charged = min of what we need vs realistic capacity
      const actuallyCharged = Math.min(allocation.chargeNeeded, realisticCapacity);

      trackedKwh += actuallyCharged;
      trackedTotalCost += actuallyCharged * window.minPrice;
      trackedBatteryCost = trackedKwh > 0 ? trackedTotalCost / trackedKwh : trackedBatteryCost;
      trackedAvailable = Math.max(0, trackedKwh - (socMin / 100 * batteryCapacity));
    }

    // SECTION 4.8.1: Check if strategic target not yet reached
    if (isStrategicPeriod && allocation.window.isStrategic) {
      const strategicTargetKwh = (batteryCapacity * strategicTargetSoC / 100);
      const stillNeedToCharge = strategicTargetKwh - trackedKwh;

      // If we haven't reached strategic target, mark next windows as strategic too
      if (stillNeedToCharge > 0.5 && windowIndex + 1 < cheapWindows.length) {
        const nextWindow = cheapWindows[windowIndex + 1];
        // Only if next window is also reasonably cheap (within 10% of strategic threshold)
        if (nextWindow.avgPrice < strategicPriceThreshold * 1.10) {
          nextWindow.isStrategic = true;
          nextWindow.strategicCarryForward = stillNeedToCharge;
        }
      }
    }

    if (allocation.allocatedGaps.length > 0) {
      const immediateGap = allocation.allocatedGaps[0];
      const consumedByGap = immediateGap.energyNeeded / Math.sqrt(efficiency);
      trackedKwh -= consumedByGap;
      trackedKwh = Math.max((socMin / 100) * batteryCapacity, trackedKwh);
      trackedAvailable = Math.max(0, trackedKwh - (socMin / 100 * batteryCapacity));
    }

    trackedKwh = Math.min((socMax / 100) * batteryCapacity, trackedKwh);

    allocations.push(allocation);
  }

  return allocations;
}

const windowAllocations = allocateGapsToWindows();

// =============================================================================
// SECTION 5: PASS 4 - DISTRIBUTE CHARGING TO CHEAPEST SLOTS
// =============================================================================

// SECTION 5.1: For each window, create charging plan
function createChargingPlan() {
  const chargingPlan = new Map();

  windowAllocations.forEach(allocation => {
    const window = allocation.window;

    if (allocation.chargeNeeded < 0.1) {
      // No charging needed
      allocation.plannedChargeKwh = 0;
      allocation.reason = 'Battery sufficient';
      return;
    }

    // SECTION 5.2: Sort window slots by price (cheapest first)
    const sortedSlots = window.slots
      .map(slotIndex => ({
        index: slotIndex,
        price: Math.round(slots[slotIndex].import_price * 100) / 100, // Round to 2 decimals
        hasWaterHeating: waterHeatingSlots.has(slotIndex)
      }))
      .sort((a, b) => a.price - b.price);

    // SECTION 5.3: Iterative SoC-target charging
    // Keep adding cheapest slots until projected SoC reaches target

    const baseTargetKwh = allocation.isAbsoluteTarget ?
      (strategicTargetSoC / 100 * batteryCapacity) :
      allocation.batteryStateAtStart.kwh + (allocation.actualDeficit / Math.sqrt(efficiency));

    // Add 1 kWh safety buffer for strategic targets to account for losses
    const targetKwh = allocation.isAbsoluteTarget ?
      Math.min(baseTargetKwh + 1.0, socMax / 100 * batteryCapacity) :
      baseTargetKwh;

    let currentProjectedKwh = allocation.batteryStateAtStart.kwh;
    let slotCount = 0;

    for (const slotInfo of sortedSlots) {
      // Stop if we've reached the target SoC
      if (currentProjectedKwh >= targetKwh - 0.1) break; // 0.1 kWh tolerance

      const slotIndex = slotInfo.index;

      // SECTION 5.4: Calculate real available power for this slot
      let availablePower = inverterLimit;

      // Subtract water heating if present
      if (slotInfo.hasWaterHeating) {
        availablePower -= waterPowerKw;
      }

      // Subtract expected load during this slot
      const netLoad = Math.max(0, slots[slotIndex].adjusted_load_kwh - slots[slotIndex].adjusted_pv_kwh);
      availablePower -= netLoad * 4;

      // SECTION 5.5: Determine actual charge power
      const maxChargePower = Math.min(
        maxChargeKw,
        availablePower
      );

      if (maxChargePower > 0.1) {
        const chargeKwh = maxChargePower * 0.25;
        const usableChargeKwh = chargeKwh * Math.sqrt(efficiency);

        // CRITICAL FIX: If this slot has water heating, it will also discharge battery
        // We need to account for this in the projection
        let netBatteryGain = usableChargeKwh;

        if (slotInfo.hasWaterHeating) {
          const waterDischargeKwh = waterPowerKw * 0.25 / Math.sqrt(efficiency);
          netBatteryGain -= waterDischargeKwh;
        }

        chargingPlan.set(slotIndex, {
          chargeKwh: chargeKwh,
          chargeKw: maxChargePower,
          price: slotInfo.price,
          windowIndex: allocation.windowIndex,
          responsibility: allocation.chargingFor.join(', '),
          totalResponsibility: allocation.totalResponsibility,
          deficit: allocation.actualDeficit,
          slotInWindow: slotCount,
          projectedKwhAfter: currentProjectedKwh + netBatteryGain
        });

        currentProjectedKwh += netBatteryGain;  // Use NET gain, not gross charging
        slotCount++;
      }
    }

    allocation.plannedChargeKwh = currentProjectedKwh - allocation.batteryStateAtStart.kwh;
    allocation.slotsUsed = slotCount;
    allocation.finalBatteryKwh = currentProjectedKwh;
  });

  return chargingPlan;
}

const chargingPlan = createChargingPlan();

// =============================================================================
// SECTION 6: HELPER FUNCTIONS
// =============================================================================

// SECTION 6.1: Calculate protective SoC for exports
function calculateProtectiveSoC(currentSlotIndex, currentProjectedKwh) {
  // Find relevant window responsibility
  let relevantResponsibility = null;

  for (const allocation of windowAllocations) {
    if (currentSlotIndex <= allocation.window.endSlot && allocation.allocatedGaps.length > 0) {
      const firstGap = allocation.allocatedGaps[0];
      if (currentSlotIndex < firstGap.endSlot) {
        relevantResponsibility = allocation;
        break;
      }
    }
  }

  if (!relevantResponsibility || relevantResponsibility.totalResponsibility === 0) {
    return socMin;
  }

  // Calculate energy still needed from current point
  let energyNeeded = 0;
  for (const gap of relevantResponsibility.allocatedGaps) {
    for (let i = Math.max(currentSlotIndex, gap.startSlot); i < gap.endSlot && i < slots.length; i++) {
      const slot = slots[i];
      if (slot.import_price > batteryCost + batteryUseMargin) {
        energyNeeded += Math.max(0, slot.adjusted_load_kwh - slot.adjusted_pv_kwh);
      }
    }
  }

  energyNeeded *= sIndex;

  const protectiveKwh = energyNeeded / Math.sqrt(efficiency);
  const protectiveSoC = Math.max(socMin, (protectiveKwh / batteryCapacity) * 100);
  const currentSoCPercent = (currentProjectedKwh / batteryCapacity) * 100;

  return Math.min(protectiveSoC, currentSoCPercent);
}

// =============================================================================
// SECTION 7: PASS 5 - EXECUTE SCHEDULE
// =============================================================================

let projectedKwh = (currentSoC / 100) * batteryCapacity;
let projectedSoCCurrent = currentSoC;
let projectedBatteryCost = parseFloat(batteryCost);
let projectedTotalCost = projectedKwh * batteryCost;

const schedule = slots.map((slot, index) => {
  const kwh_before = projectedKwh;
  const cost_before = projectedBatteryCost;

  // SECTION 7.1: Initialize slot
  const scheduleSlot = {
    slot_number: index,
    slot_datetime: slot.slot_start,

    // Inputs from upstream
    spot_price_sek: slot.import_price || 0,
    export_price_sek: slot.export_price || 0,
    percentile: slot.import_percentile || 50,
    price_category: slot.price_category || 'normal',
    pv_forecast_kwh: slot.adjusted_pv_kwh || 0,
    load_forecast_kwh: slot.adjusted_load_kwh || 0,
    deficit_kwh: slot.deficit_kwh || 0,
    surplus_kwh: slot.surplus_kwh || 0,
    net_load_kw: (slot.adjusted_load_kwh - slot.adjusted_pv_kwh) * 4,

    // State
    soc_before: projectedSoCCurrent,
    kwh_before: kwh_before,

    // Decisions (defaults)
    action: 'hold',
    power_kw: 0,
    battery_charge_kw: 0,
    battery_discharge_kw: 0,
    grid_import_kw: 0,
    grid_export_kw: 0,
    water_heating_kw: 0,
    water_from_pv: 0,
    water_from_battery: 0,
    water_from_grid: 0,
    soc_target: Math.round(projectedSoCCurrent),

    // Economics
    battery_cost_sek: projectedBatteryCost,
    expected_cost_sek: 0,
    expected_revenue_sek: 0,
    expected_profit_sek: 0,

    decision_reason: '',
    decision_priority: 0
  };

  // SECTION 7.2: Handle water heating with dynamic source selection
  const hasWaterHeating = waterHeatingSlots.has(index);
  if (hasWaterHeating) {
    const waterNeedKwh = waterPowerKw * 0.25;
    const waterNeedKw = waterPowerKw;
    const pvSurplus = Math.max(0, slot.adjusted_pv_kwh - slot.adjusted_load_kwh);
    const batteryAvailable = projectedKwh - (socMin / 100 * batteryCapacity);
    const batteryThreshold = projectedBatteryCost + batteryWaterMargin;

    // Priority 1: Use PV surplus (free)
    const waterFromPV = Math.min(pvSurplus, waterNeedKwh);
    scheduleSlot.water_from_pv = waterFromPV;

    let waterRemaining = waterNeedKwh - waterFromPV;

    // Priority 2: Use battery if economical
    if (waterRemaining > 0 && scheduleSlot.spot_price_sek > batteryThreshold && batteryAvailable > 0) {
      const waterFromBattery = Math.min(batteryAvailable, waterRemaining);
      scheduleSlot.water_from_battery = waterFromBattery;

      // Discharge battery
      const dischargeKwh = waterFromBattery / Math.sqrt(efficiency);
      projectedKwh -= dischargeKwh;
      projectedTotalCost -= (dischargeKwh * projectedBatteryCost);
      scheduleSlot.battery_discharge_kw += waterFromBattery * 4;

      waterRemaining -= waterFromBattery;
    }

    // Priority 3: Use grid for remainder
    if (waterRemaining > 0) {
      scheduleSlot.water_from_grid = waterRemaining;
      scheduleSlot.grid_import_kw += waterRemaining * 4;
      scheduleSlot.expected_cost_sek += scheduleSlot.spot_price_sek * waterRemaining;
    }

    scheduleSlot.water_heating_kw = waterNeedKw;
    scheduleSlot.decision_reason = `Water(PV:${waterFromPV.toFixed(2)} Bat:${scheduleSlot.water_from_battery.toFixed(2)} Grid:${scheduleSlot.water_from_grid.toFixed(2)}) + `;

    // Set soc_target to allow battery discharge if needed
    scheduleSlot.soc_target = socMin;
  }

  // Calculate net load and battery state
  const netLoad = slot.adjusted_load_kwh - slot.adjusted_pv_kwh;
  const batteryAvailable = projectedKwh - (socMin / 100 * batteryCapacity);
  const batterySpace = (socMax / 100 * batteryCapacity) - projectedKwh;

  // Check if this slot is in charging plan
  const chargeInstruction = chargingPlan.get(index);

  // Check if current slot is in a cheap window (for hold logic)
  const inCheapWindow = cheapWindows.some(w =>
    index >= w.startSlot && index <= w.endSlot
  );

  // =============================================================================
  // DECISION LOGIC
  // =============================================================================

  // SECTION 7.3: PRIORITY 1 - Execute charging plan
  if (chargeInstruction && batterySpace > 0.1) {
    const chargeKw = Math.min(chargeInstruction.chargeKw, batterySpace * 4);

    scheduleSlot.action = 'charge';
    scheduleSlot.battery_charge_kw = chargeKw;
    scheduleSlot.grid_import_kw += chargeKw;
    scheduleSlot.soc_target = socMax;
    scheduleSlot.expected_cost_sek += scheduleSlot.spot_price_sek * (chargeKw * 0.25);
    scheduleSlot.decision_reason += `Charge @${scheduleSlot.spot_price_sek.toFixed(3)} (${chargeInstruction.responsibility})`;
    scheduleSlot.decision_priority = 1;

    // Update battery state
    const chargeKwh = chargeKw * 0.25 * Math.sqrt(efficiency);
    projectedKwh += chargeKwh;

    const chargeCost = chargeKw * 0.25 * scheduleSlot.spot_price_sek;
    projectedTotalCost += chargeCost;

    if (projectedKwh > 0) {
      projectedBatteryCost = projectedTotalCost / projectedKwh;
    }

    // Handle any load with grid
    if (netLoad > 0) {
      scheduleSlot.grid_import_kw += netLoad * 4;
      scheduleSlot.expected_cost_sek += scheduleSlot.spot_price_sek * netLoad;
    }
  }

  // SECTION 7.4: PRIORITY 2 - Handle load
  else if (netLoad > 0) {
    // CRITICAL: If in cheap window, HOLD battery (don't discharge)
    // MPC principle: preserve battery during cheap periods for expensive periods ahead
    if (inCheapWindow && batteryAvailable >= netLoad) {
      // Hold battery, use grid for load
      if (!hasWaterHeating) {
        scheduleSlot.action = 'hold';
      }
      scheduleSlot.grid_import_kw += netLoad * 4;
      scheduleSlot.soc_target = Math.round(projectedSoCCurrent); // Maintain current SoC
      scheduleSlot.expected_cost_sek += scheduleSlot.spot_price_sek * netLoad;
      scheduleSlot.decision_reason += `Hold in cheap window @${scheduleSlot.spot_price_sek.toFixed(3)} (preserve for expensive periods)`;
      scheduleSlot.decision_priority = 2;

    } else if (batteryAvailable >= netLoad &&
               scheduleSlot.spot_price_sek > projectedBatteryCost + batteryUseMargin) {
      // Battery is cheaper AND not in cheap window
      scheduleSlot.action = 'discharge';
      scheduleSlot.battery_discharge_kw += Math.min(netLoad * 4, maxDischargeKw);
      scheduleSlot.soc_target = socMin;
      scheduleSlot.decision_reason += `Battery (grid ${scheduleSlot.spot_price_sek.toFixed(3)} > bat ${projectedBatteryCost.toFixed(3)})`;
      scheduleSlot.decision_priority = 2;

      const dischargeKwh = netLoad / Math.sqrt(efficiency);
      projectedKwh -= dischargeKwh;
      projectedTotalCost -= (dischargeKwh * projectedBatteryCost);

    } else {
      // Grid is cheaper
      if (!hasWaterHeating) {
        scheduleSlot.action = 'hold';
      }
      scheduleSlot.grid_import_kw += netLoad * 4;
      scheduleSlot.soc_target = Math.round(projectedSoCCurrent);
      scheduleSlot.expected_cost_sek += scheduleSlot.spot_price_sek * netLoad;

      if (batteryAvailable < netLoad) {
        scheduleSlot.decision_reason += `Grid (battery low)`;
      } else {
        scheduleSlot.decision_reason += `Grid (cheaper @${scheduleSlot.spot_price_sek.toFixed(3)})`;
      }
      scheduleSlot.decision_priority = 3;
    }
  }

  // SECTION 7.5: PRIORITY 3 - PV surplus
  else if (netLoad < 0) {
    const surplusKwh = Math.abs(netLoad);
    const chargeFromPV = Math.min(surplusKwh, batterySpace);

    if (chargeFromPV > 0.001) { // Charge any surplus > 1 Wh
      scheduleSlot.action = 'pv_charge';
      scheduleSlot.battery_charge_kw = chargeFromPV * 4;
      scheduleSlot.soc_target = socMin; // Allow discharge if needed (e.g., water heating with clouds)
      scheduleSlot.decision_reason += `PV charges ${chargeFromPV.toFixed(2)} kWh`;
      scheduleSlot.decision_priority = 4;

      projectedKwh += chargeFromPV * Math.sqrt(efficiency);

      if (projectedKwh > 0) {
        projectedBatteryCost = projectedTotalCost / projectedKwh;
      }

    } else {
      // Battery full, tiny PV surplus - hold but keep battery available
      if (!hasWaterHeating) {
        scheduleSlot.action = 'hold';
      }
      scheduleSlot.soc_target = socMin; // Allow battery use if needed
      scheduleSlot.decision_reason += `Hold (PV surplus, battery at ${projectedSoCCurrent.toFixed(1)}%)`;
      scheduleSlot.decision_priority = 5;
    }
  }

  // SECTION 7.6: PRIORITY 4 - Export opportunity
  else {
    const exportOpp = arbitrageData.export_opportunities?.find(e => e.slot === index);

    if (exportOpp && batteryAvailable > 1) {
      const protectiveSoC = calculateProtectiveSoC(index, projectedKwh);
      const protectiveKwh = (protectiveSoC / 100) * batteryCapacity;
      const actuallyAvailable = Math.max(0, projectedKwh - protectiveKwh);
      const exportKwh = Math.min(actuallyAvailable, maxDischargeKw * 0.25);

      if (exportKwh > 0.1 && exportOpp.profit_per_kwh > 0) {
        scheduleSlot.action = 'export';
        scheduleSlot.battery_discharge_kw += exportKwh * 4;
        scheduleSlot.grid_export_kw = exportKwh * 4;
        scheduleSlot.soc_target = Math.round(protectiveSoC);
        scheduleSlot.expected_revenue_sek = scheduleSlot.export_price_sek * exportKwh;
        scheduleSlot.expected_profit_sek = exportOpp.profit_per_kwh * exportKwh;
        scheduleSlot.decision_reason += `Export ${exportKwh.toFixed(2)} kWh (profit ${exportOpp.profit_per_kwh.toFixed(3)})`;
        scheduleSlot.decision_priority = 6;

        const dischargeKwh = exportKwh / Math.sqrt(efficiency);
        projectedKwh -= dischargeKwh;
        projectedTotalCost -= (dischargeKwh * projectedBatteryCost);
      } else {
        if (!hasWaterHeating) {
          scheduleSlot.action = 'hold';
        }
        scheduleSlot.soc_target = Math.round(projectedSoCCurrent);
        scheduleSlot.decision_reason += `Hold (export unsafe)`;
        scheduleSlot.decision_priority = 7;
      }
    } else {
      if (!hasWaterHeating) {
        scheduleSlot.action = 'hold';
      }
      scheduleSlot.soc_target = Math.round(projectedSoCCurrent);
      scheduleSlot.decision_reason += `Hold`;
      scheduleSlot.decision_priority = 7;
    }
  }

  // SECTION 7.7: Update battery state and costs
  projectedKwh = Math.max((socMin/100) * batteryCapacity, Math.min((socMax/100) * batteryCapacity, projectedKwh));
  projectedSoCCurrent = (projectedKwh / batteryCapacity) * 100;

  scheduleSlot.soc_projected = Math.round(projectedSoCCurrent * 10) / 10;
  scheduleSlot.kwh_projected = Math.round(projectedKwh * 100) / 100;
  scheduleSlot.power_kw = scheduleSlot.battery_charge_kw - scheduleSlot.battery_discharge_kw;
  scheduleSlot.projected_battery_cost = projectedBatteryCost;

  return scheduleSlot;
});

// =============================================================================
// SECTION 8: OUTPUT WITH COMPREHENSIVE DEBUG
// =============================================================================

return [{
  json: {
    timestamp: $now.toISO(),
    schedule: schedule,

    // SECTION 8.1: Summary statistics
    summary: {
      starting_soc: currentSoC,
      ending_soc: Math.round(projectedSoCCurrent * 10) / 10,
      charge_slots: schedule.filter(s => s.action === 'charge' || s.action === 'pv_charge').length,
      discharge_slots: schedule.filter(s => s.action === 'discharge').length,
      export_slots: schedule.filter(s => s.action === 'export' || s.grid_export_kw > 0).length,
      water_heating_slots: schedule.filter(s => s.water_heating_kw > 0).length,
      total_cost: Math.round(schedule.reduce((sum, s) => sum + s.expected_cost_sek, 0) * 100) / 100,
      total_revenue: Math.round(schedule.reduce((sum, s) => sum + s.expected_revenue_sek, 0) * 100) / 100,
      net_profit: Math.round((schedule.reduce((sum, s) => sum + s.expected_revenue_sek, 0) -
                              schedule.reduce((sum, s) => sum + s.expected_cost_sek, 0)) * 100) / 100
    },

    debug: {
      node: "Decision Maker v6.3",
      architecture: "Multi-pass MPC with Integrated Water Heating - FIXED",

      key_metrics: {
        battery_cost_initial: batteryCost,
        battery_cost_final: projectedBatteryCost,
        s_index: sIndex,
        cheap_windows_found: cheapWindows.length,
        water_heating_scheduled: !dailyWaterHeated,
        water_heating_slots_count: waterSchedule.slots.length,
        total_charge_kwh: Math.round(schedule.filter(s => s.action === 'charge')
          .reduce((sum, s) => sum + s.battery_charge_kw * 0.25, 0) * 100) / 100,
        total_discharge_kwh: Math.round(schedule.filter(s => s.action === 'discharge')
          .reduce((sum, s) => sum + s.battery_discharge_kw * 0.25, 0) * 100) / 100,
        total_pv_charge_kwh: Math.round(schedule.filter(s => s.action === 'pv_charge')
          .reduce((sum, s) => sum + s.battery_charge_kw * 0.25, 0) * 100) / 100
      },

      // SECTION 8.1.5: Water heating analysis
      water_heating_analysis: {
        daily_water_kwh: dailyWaterKwh,
        minimum_kwh: waterMinimumKwh,
        already_heated: dailyWaterHeated,
        scheduled_slots: waterSchedule.slots.length,
        scheduled_hours: waterSchedule.total_hours,
        total_cost_sek: Math.round(waterSchedule.total_cost_sek * 100) / 100,
        strategy: waterSchedule.strategy,
        skipped_reason: waterSchedule.skipped_reason,
        source_breakdown: {
          from_pv_kwh: Math.round(schedule.reduce((sum, s) => sum + s.water_from_pv, 0) * 100) / 100,
          from_battery_kwh: Math.round(schedule.reduce((sum, s) => sum + s.water_from_battery, 0) * 100) / 100,
          from_grid_kwh: Math.round(schedule.reduce((sum, s) => sum + s.water_from_grid, 0) * 100) / 100
        },
        battery_threshold: batteryWaterMargin,
        slots_detail: schedule
          .filter(s => s.water_heating_kw > 0)
          .slice(0, 10)
          .map(s => ({
            slot: s.slot_number,
            time: s.slot_datetime.substring(11, 16),
            price: Math.round(s.spot_price_sek * 1000) / 1000,
            pv: Math.round(s.water_from_pv * 100) / 100,
            battery: Math.round(s.water_from_battery * 100) / 100,
            grid: Math.round(s.water_from_grid * 100) / 100
          }))
      },

      // SECTION 8.2: Pass 1 - Windows identified
      pass1_cheap_windows: cheapWindows.map(w => ({
        index: w.index,
        start_slot: w.startSlot,
        end_slot: w.endSlot,
        start_time: w.startTime.substring(11, 16),
        end_time: w.endTime.substring(11, 16),
        duration_hours: w.duration,
        slots_count: w.slots.length,
        price_min: Math.round(w.minPrice * 1000) / 1000,
        price_max: Math.round(w.maxPrice * 1000) / 1000,
        price_avg: Math.round(w.avgPrice * 1000) / 1000,
        theoretical_capacity_kwh: Math.round(w.theoreticalCapacity * 100) / 100
      })),

      // SECTION 8.3: Pass 2 - Simulated battery depletion
      pass2_window_states: Array.from(windowStates.values()).map(state => ({
        window_index: state.windowIndex,
        slot: state.slot,
        time: state.time.substring(11, 16),
        simulated_kwh: Math.round(state.kwh * 100) / 100,
        simulated_soc: Math.round(state.soc * 10) / 10,
        available_kwh: Math.round(state.available * 100) / 100
      })),

      // SECTION 8.4: Pass 3 - Gap allocations
      pass3_gap_allocations: windowAllocations.map(a => ({
        window_index: a.windowIndex,
        window_time: a.window.startTime.substring(11, 16),
        is_strategic: a.window.isStrategic || false,
        battery_at_start_kwh: Math.round(a.batteryStateAtStart.kwh * 100) / 100,
        battery_at_start_soc: Math.round(a.batteryStateAtStart.soc * 10) / 10,
        available_kwh: Math.round(a.batteryStateAtStart.available * 100) / 100,
        charging_for: a.chargingFor,
        total_responsibility_kwh: Math.round(a.totalResponsibility * 100) / 100,
        actual_deficit_kwh: Math.round(a.actualDeficit * 100) / 100,
        charge_needed_kwh: Math.round(a.chargeNeeded * 100) / 100,
        planned_charge_kwh: Math.round((a.plannedChargeKwh || 0) * 100) / 100,
        slots_used: a.slotsUsed || 0,
        final_battery_kwh: Math.round((a.finalBatteryKwh || 0) * 100) / 100,
        gaps: a.allocatedGaps.map(g => ({
          gap_index: g.gapIndex,
          from_slot: g.startSlot,
          to_slot: g.endSlot,
          duration_hours: Math.round(g.duration * 10) / 10,
          energy_needed: Math.round(g.energyNeeded * 100) / 100,
          battery_cost_used: Math.round((g.batteryCostUsed || 0) * 1000) / 1000,
          threshold: Math.round((g.threshold || 0) * 1000) / 1000,
          slots_counted: g.gapSlots ? g.gapSlots.length : 0
        }))
      })),

      // SECTION 8.4.5: Strategic analysis
      strategic_analysis: {
        is_strategic_period: isStrategicPeriod,
        pv_forecast_24h: Math.round(pvForecast24h * 100) / 100,
        avg_load_24h: Math.round(avgLoad24h * 100) / 100,
        pv_coverage_pct: avgLoad24h > 0 ? Math.round((pvForecast24h / avgLoad24h) * 100) : 0,
        strategic_threshold: strategicPriceThreshold,
        strategic_target_soc: strategicTargetSoC,
        strategic_windows_found: cheapWindows.filter(w => w.isStrategic).length,
        strategic_slots: cheapWindows.filter(w => w.isStrategic)
          .flatMap(w => w.slots.map(s => ({
            slot: s,
            time: slots[s].slot_start.substring(11, 16),
            price: Math.round(slots[s].import_price * 1000) / 1000
          }))).slice(0, 10)
      },

      // SECTION 8.5: Pass 4 - Charging plan
      pass4_charging_plan: Array.from(chargingPlan.entries())
        .sort((a, b) => a[0] - b[0])
        .map(([slotIndex, plan]) => ({
          slot: slotIndex,
          time: slots[slotIndex].slot_start.substring(11, 16),
          charge_kwh: Math.round(plan.chargeKwh * 100) / 100,
          charge_kw: Math.round(plan.chargeKw * 10) / 10,
          price: Math.round(plan.price * 1000) / 1000,
          window: plan.windowIndex,
          responsibility: plan.responsibility,
          total_resp_kwh: Math.round(plan.totalResponsibility * 100) / 100,
          deficit_kwh: Math.round(plan.deficit * 100) / 100
        })),

      // SECTION 8.6: Pass 5 - Execution sample
      pass5_execution_sample: schedule.slice(0, 30).map(s => ({
        slot: s.slot_number,
        time: s.slot_datetime.substring(11, 16),
        action: s.action,
        price: Math.round(s.spot_price_sek * 1000) / 1000,
        category: s.price_category,
        charge_kw: Math.round(s.battery_charge_kw * 10) / 10,
        discharge_kw: Math.round(s.battery_discharge_kw * 10) / 10,
        water_kw: Math.round(s.water_heating_kw * 10) / 10,
        soc: Math.round(s.soc_projected * 10) / 10,
        battery_cost: Math.round(s.projected_battery_cost * 1000) / 1000,
        reason: s.decision_reason.substring(0, 80)
      })),

      // Action summary
      action_summary: {
        charge: schedule.filter(s => s.action === 'charge').length,
        discharge: schedule.filter(s => s.action === 'discharge').length,
        pv_charge: schedule.filter(s => s.action === 'pv_charge').length,
        export: schedule.filter(s => s.action === 'export').length,
        hold: schedule.filter(s => s.action === 'hold').length,
        water_heating: schedule.filter(s => s.water_heating_kw > 0).length
      }
    }
  }
}];
