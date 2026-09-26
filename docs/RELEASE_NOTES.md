## [v2.7.1-beta] - EV Fixes & Quick Actions - 2026-09-26

**✨ New**

- **Quick action popovers**: Top Up, EV, Boost, Vacay, Risk and Water open a popover (a bottom sheet on mobile) with presets and custom values. The EV current selector now lives in the EV popover. The Auto toggle is removed, and plan status shows Last/Next rows.
- **Manual EV charging**, with an EV node for each charger on the dashboard.
- **Smarter EV planning**: charging is priced by how long it's put off, replacing the fixed daily quota. The plan updates straight away when you change a goal and shows that it's waiting while it does.
- **EV cost breakdown** and energy tracking for each charger. Past slots keep their planned EV charging.
- **Graceful fuse-limit handling**: EV charging slows down gradually near the fuse limit instead of cutting out.

**🐛 Bug Fixes**

EV charger control is more reliable. Current-based chargers now work, amps adjust to the power actually measured, goals missed during outages are caught up, and stale SOC readings are handled safely. Published Nordpool prices are now preferred over forecasts. HA sensor freshness is judged correctly, base load shows on the House node again, the load profile counts readings that cross midnight, and the logo has no stray bar.

---

## [v2.7.0-beta] - Load Balancing, Goal-Based EV Charging, Price Forecasting & Stability - 2026-09-18

> [!IMPORTANT]
> **BREAKING: EV Charging Redesigned**
> "Penalty levels" (a willingness-to-pay in SEK/kWh) are replaced by **goals**: *"have the car at 80% by 07:00"*. The old model defaulted to empty, so out of the box the EV silently never charged from surplus PV — and even tuned, it could never guarantee the car was usable by departure. Migration is automatic; set your goal on the Dashboard's EV tab.

> [!IMPORTANT]
> **New: Per-Phase Load Balancing (Main Fuse Protection)**
> Darkstar can protect your main fuse in real time without dedicated hardware, throttling EV charge current and then shedding loads in an order you choose. **Opt-in** — activates only once you set a fuse rating and per-phase sensors under Settings → Load Balancing. **Needs a fast executor tick** (5 s recommended); the 300 s default makes fuse protection nearly useless, and Darkstar will warn you.

**✨ Major Features**

- **Universal Load Balancing** — per-phase fuse protection with variable EV charge current (6 A floor, then pause). Accepts current *or* power sensors per phase (auto-detected). One drag-ordered give-way list mixing throttled chargers and on/off shed loads, each row stating what the balancer can do to it. Anti-flapping, stale-sensor fail-safe, early replan when throttling is sustained, and intervention notifications.
- **Goal-Based EV Charging** — target SoC + ready-by time + repeat rule, solved as a soft requirement so an unreachable goal never breaks the plan. Dashboard EV tab with progress and on-track status, optional Home Assistant sync (HA wins), automatic chunk-aware multi-day spreading, and fractional charging for current-type chargers so small goals no longer produce zero charging. Configurable HA value mappings for select-based chargers such as the go-e Gemini Flex.
- **Excess PV Priority Dispatch** — an ordered list of sinks replaces the single-sink setting, with the house battery implicitly first. EV surplus charging tracks *measured* surplus each tick, and commanded 1↔3-phase switching lets a 2–4 kW surplus reach the car at all.
- **Nordpool Price Forecasting (Aurora)** — LightGBM quantile model predicting D+1 to D+7 with p10/p50/p90 bands. Serves D+1 estimates before the daily auction publishes. Forecast dashboard with horizon chart, price cards, weekly outlook and a live accuracy KPI, plus a Price Advisor. Not yet wired into planning decisions.
- **Settings Search & Guides** — ~130 fields across eight tabs searchable by name, help text or everyday synonym ("breaker" finds Main Fuse). 14 plain-language guides plus a glossary, each linking to the settings it describes.
- **Dashboard** — PowerFlow highway-bus redesign with a live Load Balancer tab (phase bars vs. fuse, state and reason) that auto-opens on intervention. Battery Strategy card with sparkline, mobile tap-to-select slot panel, tri-state connection status.
- **Water Heater Switch Control** — relay-driven tanks (`switch.vvb`) now work via a new `control_type` field; previously they saved without error and silently did nothing. Manual boost is now per-device and actually writes. No migration needed.
- **Planner & Strategy** — risk-aware safety buffer cap (**behaviour change**: Risk 1–2 hold a higher reserve on hard days, Risk 4–5 slightly lower, Risk 3 unchanged), `min_export_kw` export floor, planner error taxonomy with preflight validation and retry, Open-Meteo PV baseline, persisted S-Index run history, and honest keep-on slots (no more phantom charging energy in schedule totals).

**🐛 Bug Fixes**

Around 30 fixes landed. The ones most likely to have affected you:

- **Planning silently stopped for 2 hours after saving settings** — retry timestamps mixed local time and UTC, so a 60-second backoff became a 2-hour outage with nothing in the logs. Now timezone-aware throughout, with skipped cycles logged.
- **The executor could read a half-written schedule file** — both writers are now atomic.
- **`database is locked`** — a manual executor trigger could run concurrently with a scheduled tick. Ticks are now single-flight.
- **Water heater mid-block locking never fired** — the planner read the previous schedule from the wrong path. **This changes live schedules**: heaters mid-cycle now correctly hold their remaining slots on.
- **Midnight planner crashes** from duplicate price forecasts, plus stale D+1 filtering.
- **EV fixes** — goal persistence, a double-count bug, HA sync, entity changes applying without a restart, departure-time parsing.
- Plus price-forecast accuracy and leakage, battery energy recording, action-verification false failures, load type enum, beta monitor false alarms, and the Load Balancing tab hiding before you could configure it.

**🧹 Under the Hood**

Recorder SSOT rewrite · runtime invariant monitors and fault-injection tests · executor safety hardening · atomic config writes · all dependencies exact-pinned (Node 22, pnpm 10) · hermetic CI · frontend typing and logic tests · dead code removal (battery cost tracking, write-only since December 2025, plus nine unused tables including the abandoned Antares experiment).

---

## [v2.6.2-beta] - DST Fixes, Performance & Power Limits - 2026-03-29

> [!IMPORTANT]
> **Daylight Saving Time Crash Fix**
> This release fixes a critical crash that occurred during DST transitions. The system now handles ambiguous and non-existent times safely.

**🐛 Critical Fixes**

- **DST-Safe Time Handling**: Fixed system crash during Daylight Saving Time transitions. All time calculations now use DST-aware logic to prevent ambiguous/non-existent time errors.
- **Executor Performance**: Config caching, Nordpool API fix, and sensor read guards to prevent executor freezing.
- **Settings Save**: Fixed profile entity filtering and added save buttons to all settings tabs.
- **EV Charger Migration**: Fixed migration order and departure_time type safety issues.

**✨ New Features**

- **Inverter Power Limits**: New constraints for AC output and DC input power limits. The planner now respects both battery C-rate limits and inverter power limits for safer operation.

---

## [v2.6.1-beta] - DB-First Energy Display & Recency-Weighted Training - 2026-03-20

> [!IMPORTANT]
> **BREAKING CHANGE: Today Sensors Removed**
> This release removes the requirement for `today_*` sensors. Darkstar now sources all daily energy totals from the database (SlotObservation table) instead of Home Assistant sensors. This ensures consistent data across Dashboard, ML training, and planning.
>
> **Migration Required:**
> 1. Remove all `today_*` sensors from your `config.yaml` input_sensors section
> 2. Keep your cumulative sensors (total_load_consumption, total_grid_import, etc.)
> 3. Restart Darkstar
>
> The Dashboard will now display water heating and EV charging data from the unified energy endpoint.

> [!IMPORTANT]
> **BUG FIXES**
> This release contains important fixes for EV charging replan functionality.

**✨ New Features**

- **Unified Energy Endpoint**: `/api/services/energy/today` now returns all daily energy metrics from the database, including:
    - `ev_charging_kwh` — Daily EV charging total (new field)
    - `water_heating_kwh` — Daily water heating total (new field)
    - All existing metrics (solar, load, grid import/export, battery cycles)
- **Conditional Dashboard Rendering**: The Energy Resources card now conditionally displays:
    - Solar Production (only when `has_solar: true`)
    - Battery metrics (only when `has_battery: true`)
    - Water Heating (only when `has_water_heater: true`)
    - EV Charging (only when `has_ev_charger: true`)
- **Deprecated Endpoint**: `GET /api/ha/water_today` is now deprecated. Use `/api/services/energy/today` which includes `water_heating_kwh`.
- **Recency-Weighted ML Training**: Aurora models now prioritize recent data using exponential decay weighting (30-day half-life). Models adapt faster to changing patterns without manual retraining schedules.
- **Multi-Device Support**: Added full support for configuring, planning, and controlling multiple Water Heaters and EV Chargers independently.
- **HA History API Integration**: Replaced cumulative energy sensors reliance with direct Home Assistant History API queries for more robust energy recording.
- **Battery Protection**: Planner now strictly blocks house battery discharge while EV is charging to prevent cycle degradation.
- **Parallel Sensor Reads**: Substantially improved performance by reading HA sensors concurrently via `asyncio.gather`.
- **Temporal Safety Floor**: Replaced aggregate deficit counting with temporal deficit tracking in the planner for safer constraint adherence.
- **Executor Reliability**: Implemented comprehensive timeout handling and exponential retry-with-backoff for critical Home Assistant API communications.

**🔧 Improvements**

- **Data Consistency**: Dashboard and ML training now use the same data source (SlotObservation table), eliminating discrepancies between displayed and actual energy usage.
- **Simplified Configuration**: Removed 7 `today_*` sensors from required configuration. Users now only need cumulative sensors for forecasting.
- **Database-First Architecture**: All daily energy totals are aggregated from 15-minute observations stored in SQLite, removing dependency on HA's daily sensor reset timing.
- **Simplified ML Pipeline**: Removed the separate "Error Correction" and "Auto-Tuner" layers. Recency weighting in base models achieves better accuracy with less complexity.

**🐛 Bug Fixes**

- Fixed EV replan failing silently on plug-in: now triggers schedule recalculation correctly and prevents unscheduled charging.
- Improved executor robustness: fixed EV charge silent failures, ensuring execution record integrity.
- Fixed PV forecast physics model accuracy causing prediction errors during certain conditions.
- Fixed EV charger state caching: properly clears state when `has_ev_charger` is toggled off.
- Fixed a logging crash in the planner and improved error notifications for easier troubleshooting.
- Fixed configuration migration ordering and tightened type safety for EV departure times.
- Fixed water heater temperature control in the execution tick loop.

---

## [v2.6.0-beta] - EV Charging, Inverter Profiles v2 & Onboarding - 2026-03-07

> [!IMPORTANT]
> **ELECTRIC VEHICLE CHARGING & PROFILE SYSTEM v2**
> This release introduces full EV charging support with intelligent scheduling, a completely rewritten Inverter Profile system, and a guided Startup Wizard for new users.

> [!WARNING]
> **Breaking Configuration Changes for Existing Users**
> This version includes significant configuration restructuring. Auto-migration will attempt to preserve your settings, but **please backup your `config.yaml` before upgrading**. If migration fails, you may need to start fresh. New installations are unaffected.

**✨ Major Features**

- **Electric Vehicle Charging**
    - **Smart Scheduling**: Darkstar now optimizes when your EV charges based on electricity prices, solar forecast, and your departure time. Set it, forget it, wake up to a charged car.
    - **Departure Time Constraints**: Configure when you need the car ready by (e.g., 07:00 every morning). The planner guarantees completion by the deadline while choosing the cheapest slots.
    - **Source Isolation**: The house battery will never discharge to charge your EV. Darkstar actively monitors power flow and blocks battery discharge whenever EV charging is active.
    - **Manual Charge Detection**: Even if you start charging manually (via Tesla app, physical button, or HA), Darkstar detects it and protects your house battery.
    - **Multiple Chargers**: Support for multiple EV chargers with individual settings and schedules.

- **Inverter Profiles v2 (Stable)**
    - **Declarative Profiles**: Complete rewrite of the profile system. Each inverter brand (Deye, Sungrow, Fronius, Generic) now has a clean, declarative YAML profile that defines exactly how to control it.
    - **Dynamic Settings UI**: Required control entities are now auto-generated from your selected profile. No more brand-specific fields cluttering the UI for other inverters.
    - **4 Core Modes**: Simplified to `charge`, `export`, `idle`, and `self_consumption`. Gone are the confusing composite mode workarounds.
    - **Per-Action Delays**: Profiles can now specify settle delays per action (critical for Fronius inverters).
    - **Better Error Messages**: Missing required entities are now reported clearly with guidance, not silent failures.

- **Startup Wizard**
    - **Guided Onboarding**: New users are greeted with a step-by-step wizard to configure essential settings before using the system.
    - **Progressive Disclosure**: Configure basics first, then optionally dive into advanced settings.

- **Device-Centric Settings Tabs**
    - **Logical Organization**: Settings are now organized by device: System, Parameters, Solar, Battery, EV, Water.
    - **Conditional Visibility**: Tabs only appear when the corresponding hardware is enabled. No EV? No EV tab cluttering your screen.
    - **All-in-One**: Each device tab contains ALL related settings—sensors, controls, and parameters—in one place.

**🚀 Improvements**

- **Hybrid PV Forecasting**
    - **Physics-First**: New hybrid forecasting engine combining physical irradiance models with ML corrections for improved accuracy.
    - **72-Hour Horizon**: The Forecast Horizon card now shows 3 days ahead, giving you better visibility into upcoming solar production.
    - **Open-Meteo Comparison**: Side-by-side comparison with Open-Meteo forecasts for validation.

- **Executor Reliability**
    - **Async HTTP Client**: Migrated from synchronous `requests` to async `aiohttp`. No more executor freezes when your inverter becomes unresponsive.
    - **Timeout Protection**: 5-second timeout on all Home Assistant API calls prevents the executor from hanging.
    - **Exponential Backoff**: Automatic retry with backoff for transient network errors.

- **Energy Recording**
    - **Spike Protection**: Outlier sensor readings are now filtered out, preventing garbage data from corrupting your ML models.
    - **Cumulative Sensors**: Full support for cumulative energy sensors with automatic delta calculation.
    - **Unit Normalization**: Automatic W/kW conversion based on sensor `unit_of_measurement`. Configure once, works everywhere.
    - **Deferrable Load Isolation**: EV and water heater energy consumption is now isolated from house load for cleaner ML training data.

**🛠️ Technical Improvements**

- **Non-Blocking Validation**: Configuration warnings no longer block saves. Configure incrementally across tabs without getting stuck.
- **Configuration Incomplete Banner**: Persistent banner shows missing required settings with direct links to the relevant tab.
- **SoC Oscillation Fix**: Removed the emergency charge override that caused battery SoC to oscillate when set near minimum.
- **Forecast Timestamp Alignment**: Fixed bug where forecasts showed zeros due to timestamp misalignment with price slots.

---

## [v2.5.13-beta] - Sungrow Composite Entity Fixes - 2026-02-12

> [!IMPORTANT]
> **SUNGROW COMPOSITE MODE & DYNAMIC UI**
> This release fixes critical issues with Sungrow composite mode entities and introduces a dynamic, profile-driven Settings UI that adapts to your inverter's specific capabilities.

**✨ Key Enhancements**

- **Sungrow Composite Fixes (REV F56)**
    - **Missing Entity Safety**: Missing composite entities (like Forced Charge/Discharge Command) are no longer silently skipped. They now produce a clear "Action Failed" result in the Execution History and a health warning.
    - **Profile Cleanup**: Standardized Sungrow entity requirements, moving `ems_mode` and `forced_charge_discharge_cmd` to required status for reliable control.
    - **Duplicate Removal**: Removed redundant `export_power_limit` logic in favor of unified `grid_max_export_power` control.

- **Dynamic Settings UI (REV F56)**
    - **Profile-Driven Forms**: The Settings UI now dynamically generates fields based on your Inverter Profile's metadata. No more Deye-specific fields appearing for Sungrow users.
    - **Custom Entity Support**: Added native UI support for "Custom Entities" defined in profiles, ensuring they are mapped correctly in `executor.inverter.custom_entities`.

- **Runtime Error Visibility**
    - **Health Reporting**: The System Dashboard now reports missing profile-required entities as health warnings with clear guidance.
    - **Initialization Validation**: The system now performs deeper validation of your inverter configuration on every startup and config save.

### 📜 Full Changelog

*   **REV // F56:** Sungrow Composite Entity Configuration & Dynamic UI
*   **REV // F56:** Profile-driven Health Reporting for missing entities
*   **REV // F56:** ActionResult implementation for failed composite mode auxiliary entities

---

## [v2.5.12-beta] - UX Polish, Config Safety & Structure - 2026-02-01

> [!IMPORTANT]
> **UX POLISH & CONFIGURATION SAFETY**
> This release brings User Experience improvements including "Unsaved Changes" protection, real-time feedback, and a smarter Configuration merging system that respects your file structure.

**✨ Key Enhancements**

- **UX Polish & Safety (Rev UI13, UI14, UI15, UI7)**
    - **Unsaved Changes**: You will now be warned before navigating away if you have unsaved changes in Settings.
    - **Real-Time Feedback**: The "Run Planner" button now shows real-time progress (e.g., "Fetching prices...", "Solving...").
    - **Chart Improvements**: Fixed zoom behavior, added a "Reset Zoom" button, and simplified overlays.
    - **Mobile**: The Power Flow card is now cleaner and extensible.

- **Configuration Intelligence (Rev DX14, F42)**
    - **Structure-Aware Merge**: When Darkstar updates your `config.yaml`, it now preserves your key order and comments, inserting new keys exactly where they belong.
    - **Ghost Busters**: Fixed an issue where deleted entities would reappear from defaults.

    > [!WARNING]
    > **Structure Reset**: The new merging logic will reorganize your `config.yaml` to match the official structure of `config.default.yaml`. If you have heavily customized the order or grouping of keys, these changes will be reset to the standard layout. Your values and custom comments on non-standard keys are preserved. A backup is automatically created at `config.yaml.bak` before any changes are applied.

- **Executor Robustness (Rev F44)**
    - **Domain Awareness**: The executor now automatically handles `input_select` vs `select` and `input_number` vs `number` entities.
    - **Safety Guard**: Prevents accidental attempts to control read-only `sensor` entities.

### 📜 Full Changelog

*   **REV DX14:** Config Soft Merge Improvement (Structure-aware)
*   **REV UI15:** Chart Overlay Cleanup
*   **REV UI14:** UX Polish & Config Documentation (Zoom, Timer, Planner Progress)
*   **REV UI13:** Unsaved Changes Warning (Banner & Navigation Guard)
*   **REV UI7:** Mobile Polish & Extensible Architecture
*   **REV F44:** Executor Domain Awareness & Safety
*   **REV F43-HOTFIX:** Fix Darkstar-Dev Dockerfile Build
*   **REV F42:** Ghost Notifications & Default Config Cleanup

---

## [v2.5.11-beta] - Dynamic Water Heating & Advanced Mode - 2026-01-26

> [!IMPORTANT]
> **DYNAMIC WATER HEATING & ADVANCED MODE**
> This release marks a major milestone in Darkstar's transition to an intelligent agent. It introduces a "Dynamic Water Heating" engine that adapts to your comfort preferences, a "Trust-but-Verify" execution system that proves commands work, and a completely redesigned "Advanced Mode" for settings.

**☀️ Key Enhancements**

- **Dynamic Water Heating (Rev K16, K23, K24)**
    - **Dynamic Windows**: Comfort levels 1-5 now intelligently resize heating blocks. Level 1 (Economy) groups heating into large, efficient chunks. Level 5 (Maximum) allows frequent top-ups for endless hot water.
    - **Performance**: The new Kepler solver optimization significantly reduces solve times.
    - **Smart Penalties**: Fully tunable penalties for block length, starts, and reliability.

- **Advanced Mode & UI Polish (Rev UI10, UI12, K17)**
    - **Standard Mode**: A clean, minimal interface for everyday use.
    - **Advanced Mode**: Toggle this to unlock technical parameters, solver constraints, and the moved embedded Debug tab.
    - **Animations**: Smooth transitions when toggling modes.

- **Trust-but-Verify Execution (Rev UI11)**
    - **Entity Visibility**: See exactly which Home Assistant entity (e.g., `number.inverter_max_charge`) is being controlled.
    - **Status Verification**: A new "traffic light" system in Execution History shows if a command succeeded (Green), failed (Red), or was skipped (Blue).
    - **Shadow Mode**: Clearly distinguishes "What If" shadow actions from real commands.

**🛠️ Technical Improvements**

- **Critical Executor Fix (Rev F38)**: Rewrote the Executor Engine to be fully `async`, eliminating race conditions and `RuntimeError` crashes during heavy load.
- **Test Suite Stabilization (Rev F39)**: Fixed all regression tests. reliable green builds are back.
- **Configuration Exposure (Rev K17)**: Almost every hardcoded solver constraint is now exposed in `config.yaml` for power users.
- **Battery SoC Fallback (Rev H5)**: The system now persists the last known Battery SoC during sensor outages, preventing charts from dropping to 0%.

### 📜 Full Changelog

*   **REV // F40:** Fix Database Schema Drift (action_results Migration)
*   **REV K24:** Dynamic Water Comfort Windows (Adaptive block sizing)
*   **REV F39:** Test Suite Stabilisation (0 failures)
*   **REV H5:** Battery SoC Fallback (Data Persistence)
*   **REV F38:** Critical Asyncio Executor Fix (Engine Stability)
*   **REV K23:** Water Comfort Multi-Parameter Control (Economy vs Comfort scaling)
*   **REV UI12:** Move Debug Tab to Settings (Advanced Mode integration)
*   **REV UI11:** Enhanced Execution History (Entity visibility & Verification)
*   **REV UI10:** Advanced Settings Mode (Clean UI vs Power User UI)
*   **REV K17:** Configuration Exposure & Polish (Solver constraints)
*   **REV K16:** Water Heating Optimization (Soft constraints & Performance)

---

## [v2.5.10-beta] - Add-on Solver Stability Fix (CBC) - 2026-01-22

> [!IMPORTANT]
> **CRITICAL STABILITY FIX FOR HA ADD-ON**
> This release resolves the Infinite Hang issue in `Kepler` by switching the solver engine.

**🐛 Critical Fix**

- **Solver Engine Switch (GLPK -> CBC)**: The Home Assistant Add-on now uses the **CBC (Coin-OR Branch and Cut)** solver bundled with `PuLP` instead of the system-installed `GLPK`.
    - **Why?**: The new "Water Start Detection" and "Battery Optimization" features (v2.5.0+) created Mixed-Integer constraints that caused GLPK to hang indefinitely ("THEN NOTHING" behavior). CBC handles this complexity robustly.
    - **Impact**: Complex schedules (Water + Battery) now solve in ~30-90s instead of hanging forever.

- **Dependency Update**: Added `libgomp1` to the Docker image to prevent potential threading crashes in LightGBM/OpenMP on Debian-based add-ons.

**Upgrade Notes**
- **Transparent Upgrade**: No config changes required. The solver switch is internal to the container.
- **Verification**: Logs will now show `Kepler Solved: ...` after ~60-90s for complex plans.

---

## [v2.5.9-beta] - Kepler Battery Config Fix - 2026-01-22

**🔧 Bug Fixes**
- **Fixed Kepler battery config path**: Planner now correctly reads battery charge/discharge limits from `executor.controller.*` instead of `battery.*`
- **Added battery config validation**: Clear error messages when battery limits are misconfigured or zero
- **Fixed W/A mode toggling**: Both Watt and Ampere control modes now read from correct config paths
- **Improved config migration**: Fixed bug where migrated config keys weren't being saved

**🎯 Impact**
- Resolves flat battery schedules with no charge/discharge actions
- Battery should now properly charge/discharge based on price optimization
- Clear validation errors help identify configuration issues

---

## [v2.5.8-beta] - COMPLETE AURORA Pipeline Fix - 2026-01-22

> [!IMPORTANT]
> **FINAL COMPLETE FIX FOR AURORA ML PIPELINE**
> This release provides the definitive fix for the AURORA inference pipeline failure.
> All previous versions (v2.5.6-beta, v2.5.7-beta) were incomplete and still failed.

**🐛 Complete Fix - All 10 Locations**

- **ml/corrector.py**: Fixed ALL 6 occurrences of old data structure access
  - Lines 347, 348: Level 1 statistician corrections
  - Lines 367, 368: Level 2 ML model fallback
  - Lines 424, 425: Stats fallback values
  - Line 436: ML PV correction
  - Line 443: ML load correction
- **inputs.py**: Fixed 2 occurrences (completed in v2.5.6-beta)
- **backend/api/routers/forecast.py**: Fixed 1 occurrence (completed in v2.5.6-beta)
- **ml/simulation/data_loader.py**: Fixed 1 occurrence (completed in v2.5.6-beta)

**Technical Details**

The AURORA ML pipeline has 3 phases:
1. **Forward Generation** ✅ (was working - generates base forecasts)
2. **Correction Pipeline** ❌ (was failing - applies ML corrections)
3. **Database Persistence** ✅ (never reached due to phase 2 failure)

The error occurred in phase 2 where `predict_corrections()` calls `get_forecast_slots()` and expects nested data structure, but 6 locations in `ml/corrector.py` were still using the old flat format.

**Data Structure Migration**:
- **Old**: `rec["pv_forecast_kwh"]`, `rec["load_forecast_kwh"]`
- **New**: `rec["final"]["pv_kwh"]`, `rec["final"]["load_kwh"]`

**Comprehensive Fix Verification**:
- ✅ All 4 files that import `get_forecast_slots()` are fixed
- ✅ All 10 total occurrences of old format access are updated
- ✅ Complete pipeline flow traced and verified
- ✅ No remaining old format usage in critical path

**Impact**:
- ✅ AURORA ML pipeline completes fully end-to-end
- ✅ Battery schedules generate with proper charging/discharging actions
- ✅ ML correction models work correctly for improved forecast accuracy
- ✅ Error correction and graduation path function properly
- ✅ No more flat SoC schedules in HA add-on

---

## [v2.5.7-beta] - Complete AURORA Pipeline Fix - 2026-01-22

> [!IMPORTANT]
> **COMPLETE FIX FOR AURORA ML PIPELINE**
> This release provides the complete fix for the AURORA inference pipeline failure.
> v2.5.6-beta was incomplete and still failed - this version fixes ALL affected files.

**🐛 Complete Fix**

- **All AURORA Pipeline Consumers Fixed**: Updated all 4 files that consume `get_forecast_slots()` data to use the correct nested structure
- **ml/corrector.py**: Fixed correction pipeline data access (2 locations)
- **backend/api/routers/forecast.py**: Fixed forecast stats calculation
- **ml/simulation/data_loader.py**: Fixed simulation data loading
- **inputs.py**: Already fixed in v2.5.6-beta

**Technical Details**

The previous v2.5.6-beta fix was incomplete - it only fixed `inputs.py` but missed 3 other critical files that also consume `get_forecast_slots()` data. The error was still occurring in the correction phase of the ML pipeline.

**Complete Data Structure Migration**:
- **Old**: `rec["pv_forecast_kwh"]`, `rec["load_forecast_kwh"]`
- **New**: `rec["final"]["pv_kwh"]`, `rec["final"]["load_kwh"]`

**Impact**:
- ✅ AURORA ML pipeline completes fully without any KeyError
- ✅ Battery schedules generate with proper charging/discharging actions
- ✅ Correction models work correctly for improved accuracy
- ✅ All forecast consumers use consistent data structure

---

## [v2.5.6-beta] - AURORA Pipeline Fix - 2026-01-22

> [!IMPORTANT]
> **CRITICAL FIX FOR AURORA ML PIPELINE**
> This release fixes the AURORA inference pipeline failure that caused flat SoC schedules in v2.5.5-beta.
> The ML models were working correctly, but forecast data retrieval was broken due to a data structure mismatch.

**🐛 Critical Fix**

- **AURORA Pipeline Failure**: Fixed `KeyError: 'pv_forecast_kwh'` that caused the AURORA ML inference pipeline to fail, resulting in flat battery schedules with no charging/discharging actions.
- **Data Structure Mismatch**: Updated `inputs.py` to use the new nested forecast data structure from `ml/api.py` that was introduced in recent versions but not properly propagated.

**Technical Details**

The ML API changed the forecast data structure from flat to nested:
- **Old format**: `{"pv_forecast_kwh": 1.5, "load_forecast_kwh": 0.8}`
- **New format**: `{"final": {"pv_kwh": 1.5, "load_kwh": 0.8}, "probabilistic": {...}}`

The `inputs.py` file was still expecting the old format, causing the pipeline to crash during forecast data retrieval (not during ML inference itself).

**Impact Fixed**:
- ✅ AURORA ML pipeline completes successfully
- ✅ Proper battery charging/discharging schedules generated
- ✅ Accurate error reporting (distinguishes ML failures from data retrieval failures)
- ✅ Fallback logic works correctly when models are actually missing

---

## [v2.5.5-beta] - Critical Symlink Fix - 2026-01-22

> [!CAUTION]
> **CRITICAL HOTFIX FOR v2.5.4-beta USERS**
> If you installed v2.5.4-beta, the add-on is completely broken due to a symlink issue.
> This release fixes the critical startup crash. **Upgrade immediately.**

**🐛 Critical Fix**

- **Symlink Path Issue**: Fixed complete system failure where the application could not access persistent storage (database, ML models, logs, schedule cache). Root cause was a broken symlink that caused the app to use ephemeral storage instead of `/share/darkstar/`.

**Technical Details**

The Dockerfile incorrectly created `/app/data` as a directory, causing `ln -sf /share/darkstar /app/data` to create a **nested symlink** (`/app/data/darkstar -> /share/darkstar`) instead of a **direct symlink** (`/app/data -> /share/darkstar`).

**Impact**:
- ❌ Database errors: `sqlite3.OperationalError: no such table: slot_observations`
- ❌ ML model loading failures: `[LightGBM] [Fatal] Could not open data/ml/models/*.lgb`
- ❌ Forecast generation failures
- ❌ Schedule planning failures
- ❌ Complete add-on failure

**Changes**:
- Removed problematic `RUN mkdir -p data/ml/models` from `darkstar/Dockerfile`
- Enhanced `backend/main.py` to respect `DB_PATH` environment variable for consistency with Alembic migrations

**User Data**: All persistent data in `/share/darkstar/` is safe and untouched.

**Upgrade Path**:
- Users on v2.5.4-beta: **Must upgrade** to v2.5.5-beta
- Users on v2.5.3-beta and earlier: Can upgrade safely

---

## [v2.5.4-beta] - HA Add-on Critical Planner Fix - 2026-01-21

> [!CAUTION]
> **CRITICAL FIX FOR HA ADD-ON USERS EXPERIENCING FLAT SCHEDULES**
> If your HA Add-on deployment is producing "flat" schedules with no charge/discharge actions
> (only water heating), this release fixes the regression introduced in v2.5.0-beta.

**🐛 Critical Fixes**

- **HA Add-on Planner Regression (REV PERS2)**: Fixed complete planner failure in HA Add-on deployments where ML models were not included in Docker images, causing the planner to produce trivial schedules with zero forecasts. Solve times dropped from expected 30-60s to 0.2s with no battery actions.

- **Persistent Storage Architecture (REV PERS1)**: Fixed critical bug where ML models and `schedule.json` were stored in ephemeral container locations, being lost on every restart. All persistent data now correctly uses `/share/darkstar/` via symlinked `data/` directory.

**Root Causes Identified**

1. **Dockerfile Bug**: Only copied `ml/*.py`, not `ml/models/*.lgb` → Images shipped without baseline models
2. **Path Inconsistencies**: Mixed use of `ml/models/` and `data/ml/models/` across 10+ files
3. **Silent Failure**: `_load_models()` returned empty dict without error → Zero forecasts → Trivial optimization

**Changes Implemented**

- **Model Shipping**: `darkstar/Dockerfile` now includes 10 baseline ML models (40MB)
- **First-Boot Bootstrap**: `darkstar/run.sh` copies shipped models to persistent storage on startup
- **Robust Fallback**: When no ML models available:
  - **Load Forecast**: Uses 0.5 kWh baseline average (2 kW constant load)
  - **PV Forecast**: Uses Open-Meteo radiation data scaled by system capacity
- **Path Consistency**: Updated 10 files to use `data/ml/models` and `data/schedule.json`
- **Critical Logging**: Models missing now logs `CRITICAL` error instead of silent `Info`

**Impact**

- ✅ Fresh HA Add-on installs work immediately with baseline models
- ✅ Planner never silently runs with zero forecasts (logs critical + uses fallback)
- ✅ ML models and schedules persist across container restarts
- ✅ User-trained models are never overwritten by shipped baselines
- ✅ All code paths use consistent persistent storage locations

**Upgrade Notes**

- **First startup**: Logs will show "📦 Copied baseline model" messages (10 files)
- **Subsequent startups**: Models already present, skips copy
- **Local training**: User-trained models remain untouched in `/share/darkstar/ml/models/`

**Files Modified** (30 total)

- Core: `ml/forward.py`, `darkstar/Dockerfile`, `darkstar/run.sh`
- Path fixes: `ml/train.py`, `ml/corrector.py`, `ml/evaluate.py`, `ml/training_orchestrator.py`, `planner/output/schedule.py`, `executor/config.py`
- Scripts: `scripts/health_check.py`, `scripts/train_corrector.py`, `scripts/diagnose_ml.py`
- API: `backend/api/routers/learning.py`, `backend/api/routers/schedule.py`, `backend/services/planner_service.py`
- Docs: `docs/PLAN.md`, `docs/ARCHITECTURE.md`

---

## [v2.5.3-beta] - Critical Migration Hotfix - 2026-01-21

> [!CAUTION]
> **CRITICAL HOTFIX FOR v2.5.2-beta USERS**
> If you upgraded to v2.5.2-beta as a Home Assistant add-on and experienced database errors
> (`no such column: slot_forecasts.base_load_forecast_kwh`), this release fixes the issue.
> Your system will automatically migrate on first startup.

**🐛 Critical Fix**

- **HA Add-on Database Migration**: Fixed complete system failure for Home Assistant add-on users upgrading to v2.5.2-beta. The HA add-on startup script now automatically runs Alembic database migrations before starting the server, preventing "no such column" errors when new schema features are added.

**Technical Details**

- Added automatic database schema migration to `darkstar/run.sh` (HA add-on entrypoint)
- Migration runs after config setup but before uvicorn startup
- Idempotent and safe - preserves all existing data
- Fresh installations create database with full schema
- Already-migrated databases skip gracefully (~0.1s overhead)

**What to Expect**

- **First startup after upgrade**: Migration runs in ~0.5-2 seconds
- **Subsequent startups**: Migration is skipped (database already current)
- **New installations**: Fresh database created with correct schema

---

## [v2.5.2-beta] - ML Model Training Complete - 2026-01-21

**Core Features**
*   **Automatic ML Training (REV ARC11)**: The system now autonomously trains and updates both Main and Error Correction models based on a configurable schedule (default: Mon/Thu at 03:00).
*   **Training Orchestrator**: A unified engine (`training_orchestrator.py`) handles model lifecycle, including safety backups, graduation level checks, and partial failure recovery.
*   **Training UI**: New `ModelTrainingCard` provides real-time visibility into training status, history, and schedule.
*   **Corrector Training**: Integrated flow to train error correction models (requires "Graduate" maturity level).

**Fixes & Improvements**
*   **Chart Reliability**: Fixed history data merging and implemented smart auto-scaling that dynamically adjusts the chart window (24h vs 48h) based on available price data. Fixed timezone display issues.
*   **DevEx**: Performance reports are now correctly ignored in git to preventing repo bloat. Enforced ISO 24h date formats in UI.
*   **CI/CD**: Fixed frontend linting and backend test configuration.
*   **Documentation**: Updated docs with ARC11 completion.

---

## [v2.5.1-beta] - Recorder & Data Integrity Fixes - 2026-01-20

This maintenance release focuses on resolving critical data integrity issues in the
Recorder and ensuring accurate historical visualization and analysis.

> [!IMPORTANT]
> **v2.5.1-beta Startup Stabilization Update**
> This version includes critical fixes for config migration and database path resolution.

> [!WARNING]
> **Database Migration Required**
> This release includes significant database architecture changes (SQLAlchemy + Alembic
> migration). The system will automatically migrate your database on first startup, but this
> process may take a bit extra time for installations with large historical datasets. Backup
> your data/planner_learning.db file before updating as a precaution if you care about your recorded data.

## 🐛 Major Bug Fixes

### **Recorder & Data Pipeline**
- **Grid Meter Logic (REV F7)**: Fixed critical recorder crashes when referencing
configuration for specific grid meter types
- **Backfill Engine**: Resolved initialization failures that prevented historical data
backfilling on startup
- **Data Capture**: Improved robustness of battery power sign handling and grid import/
export recording

### **Historical Visualization**
- **History Overlay**: Fixed a major data mapping issue where historical planned actions (
charge/discharge bars, SoC targets) appeared as zero or missing in the "Schedule >
History" view
- **Forecast Comparison**: Corrected logical errors in the "Forecast vs Actual"
correlation analysis used by the Reflex learning engine

### **System Architecture & Performance**
- **Database Modernization (REV ARC9-ARC11)**: Complete migration to SQLAlchemy ORM with
Alembic migrations and full async/await implementation for all database operations
- **Kepler Optimization**: Upgraded water heating spacing constraint from O(T×S) to O(T)
linear complexity for faster planning
- **API Stability**: Fixed critical API routes that used blocking database calls, unified
router prefixes, and restored lost Aurora ML functionality

## 🚀 New Features

### **Machine Learning Pipeline (REV ML2)**
- **Load Disaggregation Framework**: Production-grade system to separate base load from
controllable appliances (water heater, EV, heat pump) for improved ML forecast accuracy
- **Smart Fallback**: Graceful degradation when individual sensors fail, with automatic
data quality monitoring

### **Structured Logging System (REV H2)**
- **JSON Logging**: Professional structured logging with rotation and management
- **Live Log Viewer**: Real-time log streaming in Debug UI with auto-scroll and viewport-
adaptive height

### **Developer Experience (REV DX4-DX5)**
- **Conventional Commits**: Enforced commit message standards with automated validation
- **UV Package Manager**: High-performance Python dependency management
- **Advanced Benchmarking**: Professional-grade performance analysis tools

## 🎨 User Experience Improvements

### **Chart & Visualization**
- **Dynamic Scaling**: Chart Y-axes now scale based on actual system configuration (solar
capacity, inverter limits)
- **Unit Conversion**: Fixed energy (kWh) to power (kW) conversion for consistent 15-
minute slot display
- **Price Visualization**: Improved price line rendering with step-line interpolation

### **Configuration & Stability**
- **Type Safety**: Robust type coercion prevents configuration corruption
- **Config Cleanup**: Removed leaked configuration keys and fixed YAML formatting issues
- **Entity Validation**: Conditional validation that respects hardware toggles (battery/
solar/water heater)
- **Executor Resilience**: Fixed pause/boost button logic flaws and UI synchronization
issues

## 🧪 Quality Assurance
- **Test Suite Stabilization**: Addressed async/sync fixture incompatibilities and schema
mismatches in the automated test suite, ensuring reliable CI/CD checks for future updates
- **Performance Monitoring**: Integrated benchmarking into development workflow
- **Documentation**: Updated architecture documentation to reflect async migration

## 🔄 Migration Notes
- **Backward Compatibility**: All changes maintain full compatibility with existing
configurations
- **Automatic Migration**: Database schema migrations handle structural changes
automatically
- **Config Soft-Merge**: New configuration keys are added without overwriting user
settings

## [v2.5.0-beta] - Configuration & Compatibility - 2026-01-16

This release solidifies the **Configuration Architecture**. It introduces a unified battery configuration, finalizes the Settings UI visibility logic, and improves startup resilience.

> [!WARNING]
> **Breaking Configuration Changes**
> *   The structure of `config.yaml` has changed (REV F17).
> *   The `system_voltage_v` and capacity settings have been moved to the new `battery:` section.
> *   **Auto-Migration:** Darkstar will attempt to automatically migrate your config file on startup (REV F18). Please back up your `config.yaml` before updating.

### ✨ New Features

#### Unified Battery Configuration (REV F17)
*   **Single Source of Truth:** Battery limits (Capacity, Max Amps/Watts) are now centralized in the new `battery:` section.
*   **Auto-Calculation:** The planner now automatically converts between Amps and Watts based on your system voltage, removing the need for duplicate manual entry.

#### Conditional Settings Polish (REV F15)
*   **Smart Visibility:** Extended the conditional logic to all parameter sections. Settings for Battery Economics, S-Index, and Water Heating Deferral are now completely hidden if the respective hardware is disabled in the System Profile.

#### Developer Experience (REV DX3)
*   **Darkstar Dev Add-on:** A new development-focused Home Assistant add-on is available for contributors, featuring faster build times (amd64 only) and tracking the `dev` branch.

### 🐛 Fixes & Improvements

*   **REV F12: Scheduler Fast Start:** The planner now runs 10 seconds after startup instead of waiting for the full hour interval.
*   **REV F18: Config Soft Merge:** Start-up now automatically fills in missing configuration keys from `config.default.yaml` without overwriting your custom settings.
*   **REV E3 Safety Patch:** Added a hard safety limit (500A) to the Watt-control logic to prevent potential integer overflow issues (9600W -> 9600A interpretation bug).

---

## [v2.4.23-beta] - Profile Foundations & Dual Sensors - 2026-01-16

### Core Features
- **Inverter Profile Foundation (REV E5)**: Established a modular profile system to support brand-specific presets. This initial release focuses on the underlying infrastructure (e.g., brand-specific visibility for SoC targets) and currently supports Generic and Deye/SunSynk profiles. *Note: Full integration for additional brands like Fronius and Victron is planned for future updates.*
- **Dual Grid Power Sensors (REV UI5)**: Added support for split import/export grid sensors. Users with separate physical sensors for grid flow can now map them individually for more accurate power flow visualization.
- **Watt-Based Inverter Control (REV E3)**: Added support for inverters controlled via Watts instead of Amperes (e.g., Fronius). The system now automatically adapts its control logic based on the selected `control_unit`.

### Improvements & Fixes
- **Relaxed Validation (REV F16)**: Disabling components like batteries or solar in the System Profile now correctly hides and relaxes validation for their dependent sensors, preventing "required field" errors for inactive hardware.
- **Test Suite Alignment**: Synchronized the automated test suite with the updated `ActionDispatcher` API, ensuring improved stability and CI reliability.

---


## [v2.4.22-beta] - Config Stability & Settings Reorganization - 2026-01-15

### Core Features
- **Settings Reorganization (REV F14)**: Major overhaul of the Settings UI. Home Assistant entities are now logically grouped into "Input Sensors" and "Control Entities", making it easier to distinguish between what Darkstar reads and what it controls.
- **Executor Overrides (REV F17)**: Exposed new battery and PV override thresholds in the UI. Added automatic configuration migration to ensure existing installations receive these new parameters without manual editing.

### Critical Fixes
- **Config Corruption**: Resolved a long-standing issue where saving settings could strip comments from `config.yaml` or corrupt newline formatting. The system now exclusively uses `ruamel.yaml` for all config operations.
- **Executor Stability**: Fixed a backend crash that occurred when the execution engine encountered "None" or unconfigured entity IDs.

### UI/UX
- **Clutter Reduction**: Removed the legacy "Live System" diagnostic card from the Executor tab.
- **History Fix**: Fixed a bug where `water_power` sensors were not correctly captured in the historical energy charts.

---


## [v2.4.21-beta] - Runtime Socket Diagnostics - 2026-01-15

### Core Features
- **Runtime Debugging (REV F11)**: Added support for runtime Socket.IO configuration overrides via URL query parameters (`?socket_path=...` and `?socket_transports=...`). This allows debugging connectivity issues in complex Ingress environments without redeploying the application.

### Observability
- **Deep Packet Logging**: Instrumented the Socket.IO Manager to log low-level packet creation and reception, providing visibility into the handshake process during connection stalls.

---

## [v2.4.20-beta] - HA Ingress Stability & Quality - 2026-01-15

### Critical Fixes
- **HA Ingress Stability (REV F11)**: Implemented the Socket.IO Manager pattern for explicit namespace handling. This resolves persistent connection stalls in Home Assistant Add-on environments behind Ingress proxies, ensuring reliable live metrics flow.

### Internal
- **Debugging & Handover**: Added a structured Socket.IO debugging handover prompt to accelerate future troubleshooting of proxy-related issues.

---

## [v2.4.19-beta] - HA Ingress Refinement & Diagnostics - 2026-01-15

### Critical Fixes
- **HA Ingress (Round 3)**: Further refined the Socket.IO path handling for Home Assistant Ingress. Added a mandatory trailing slash to the path and improved URL resolution to ensure reliable connectivity across different HA network configurations.

### Observability
- **Expanded Socket Diagnostics**: Added comprehensive packet-level logging for the Socket.IO client to aid in troubleshooting persistent connection issues in complex proxy environments.

---

## [v2.4.18-beta] - UI Persistence & Scheduler Stability - 2026-01-15

### Critical Fixes
- **HA Ingress (Round 2)**: Fixed a regression in the WebSocket connection logic where the Socket.IO `path` was incorrectly calculated. Live metrics should now reliably flow through the Home Assistant Ingress proxy.
- **Scheduler Reliability (REV F12)**: Investigated and addressed a "Delayed Start" issue where the background scheduler would wait indefinitely for its first cycle. The scheduler now triggers an immediate optimization run on startup if no previous run is detected.

---

## [v2.4.17-beta] - HA Add-on Connectivity & Observability (REV F11) - 2026-01-15

### Critical Fixes (REV F11)
- **HA Ingress Connection**: Fixed a critical bug where the WebSocket client failed to connect in Home Assistant Add-on environments. The client now correctly handles the Ingress path, resolving the "blank dashboard" and "missing live metrics" issues.
- **Data Sanitization**: Implemented "Poison Pill" protection for sensor data. The system now safely handles `NaN` and `Inf` values from HA sensors (replacing them with 0.0) to prevent JSON serialization crashes that could take down the backend.

### Observability
- **New Diagnostic Endpoints**:
    - `/api/ha-socket`: Real-time diagnostics for the HA WebSocket connection (message counts, errors, emission stats).
    - `/api/scheduler-debug`: Status of the background scheduler.
    - `/api/executor-debug`: detailed state of the execution engine.
- **Enhanced Logging**: Added deep diagnostic (`DIAG`) logging option to trace WebSocket packet flow for easier debugging of connectivity issues.

---

## [v2.4.16-beta] - Observability & Reliability - 2026-01-15

### Core Improvements
- **Production Observability**: Added `/api/ha-socket` endpoint to expose runtime statistics (messages received, errors, emission counts) for "black box" diagnosis of the HA connection.
- **Robust Data Sanitization**: Implemented "poison pill" protection in the WebSocket client. `NaN` and `Inf` sensor values are now safe-guarded to 0.0, preventing JSON serialization crashes.
- **Transport Safety**: Added error trapping to the internal Event Bus to catch and log previously silent emission failures.

### Fixes
- **HA Client**: Added deep diagnostic (`DIAG`) logging to trace packet flow during connection issues.

---

## [v2.4.15-beta] - Regression Fix & Logging - 2026-01-15

**Fixes**
*   **Executor Engine**: Fixed a regression where the list of executed actions was not being correctly populated in the execution result.
*   **Logging Refinement**: Enhanced Home Assistant WebSocket logging to respect the `LOG_LEVEL` environment variable.
*   **Historical Data Integrity**: Fixed a critical bug where historical battery charge/discharge actions were inverted in the 48h chart view. The recorder now strictly respects standard inverter sign conventions (+ discharge, - charge).

---

## [v2.4.14-beta] - Stability & Performance Plan - 2026-01-15

**Improvements**
*   **Performance Plan (REV PERF1)**: Outlined a comprehensive roadmap to optimize the Kepler MILP solver, targeting a reduction in solving time from 22s to <5s.
*   **Developer Experience**: Migrated personal git ignore rules to `.git/info/exclude` to keep the repo clean and prevent accidental commits of local config overrides.
*   **Documentation Hygiene**: Archived completed tasks (REVs F9, H3, H4) to `CHANGELOG_PLAN.md`, keeping the active plan focused.

**Fixes**
*   **Live Dashboard**: Fixed a critical bug where the Home Assistant WebSocket connection would crash or fail silently on `None` entity IDs, restoring real-time updates.
*   **Diagnostic API**: Fixed the `/api/ha-socket` endpoint to correctly report connection status.
*   **Linting**: Resolved unused imports and formatting issues in the ML pipeline.

---

## [v2.4.13-beta] - Performance & UI Polish - 2026-01-14

### Performance
- **Planner Speedup:** Fixed a critical "524 Timeout" issue by optimizing database initialization and disabling legacy debug logging.
- **Database Tools:** Added `scripts/optimize_db.py` to safe-trim oversized databases (reducing 2GB+ files to <200MB) and `scripts/profile_planner.py` for performance analysis.
- **Fix:** `training_episodes` table is no longer populated by default, preventing indefinite database growth.

### Fixes
- **HA Add-on:** Fixed a critical build issue where the Add-on served stale frontend assets, causing duplicate settings fields and other UI glitches.
- **HA Add-on:** Fixed a blank dashboard issue by correctly configuring the frontend router to handle the Home Assistant Ingress subpath.
- **UI:** Moved "HA Add-on User" banner to correct section in Settings.
- **UI:** Added warning tooltip to HA URL setting for add-on users.

---

## [v2.4.12-beta] - Executor Resilience & History Fixes - 2026-01-14

**Core Features**
*   **Executor Health Monitoring (REV E2)**: Added new health endpoint and Dashboard integration. Dashboard now shows warnings if the Executor encounters errors or if critical entities are unconfigured.
*   **Settings Validation**: The Settings UI now actively validates configuration before saving, preventing invalid states (e.g., enabling Executor without a battery sensor).
*   **Historical Accuracy (REV H4)**: Fixed persistence for historical planned actions. The "48h" chart view now correctly displays past data (SoC targets, water heating) from the database instead of relying on ephemeral files.

**Bug Fixes**
*   **Entity Configuration**: Fixed a crash where empty string entity IDs (from YAML) caused 404 errors in the Executor.
*   **UI Polish**: Removed duplicate input field rendering in Settings.

---

## [v2.4.11-beta] - Historical Charts & Security Polish - 2026-01-14


**Core Fixes**
*   **Historical Charts Restored (REV H3)**: Fixed missing planned actions in the chart history view. The API now correctly queries the `slot_plans` table to overlay charge/discharge bars and SoC targets for past time slots.
*   **Security Patch (REV F9)**: Fixed a critical path traversal vulnerability in the SPA fallback handler to prevent unauthorized file access.

**UI & Cleanups**
*   **Help System Refinement**: Simplified the help system to rely on tooltips (Single Source of Truth) and removed redundant inline helper text.
*   **"Not Implemented" Badges**: Added visual warning badges for non-functional toggles (e.g., Export Enable) to set clear user expectations.
*   **Code Hygiene**: Removed typo "calculationsWfz" and cleaned up TODO markers from user-facing text.
*   **Startup & Config Hardening**: Upgraded `run.sh` to preserve comments in `config.yaml` using `ruamel.yaml` and improved logic for manual overrides.

---

## [v2.4.10-beta] - History Fix & Config Cleanup - 2026-01-13

**Critical Bug Fix**
*   **Planned Actions History**: Fixed a bug where the chart's planned actions history would briefly appear then disappear on production deployments (Docker/HA add-on). Root cause was a race condition between schedule and history data fetching, plus the WebSocket handler not refreshing history data.

**Config & UI Cleanup**
*   **Legacy Field Removal**: Removed deprecated `charging_strategy` section from config and its associated UI fields (strategy selector, price smoothing thresholds).
*   **Orphaned Help Text**: Cleaned up orphaned config help entries for removed fields.

---

## [v2.4.9-beta] - Settings Refinement & Diagnostic Hardening - 2026-01-12

**Diagnostic & Troubleshooting**
*   **Production Diagnostic Suite**: Implemented `[SETTINGS_DEBUG]` tracing in the Settings UI to resolve environment-specific validation bugs.
*   **Debug Mode Toggle**: Added a master "Debug Mode" toggle in Advanced Experimental Features for real-time console tracing.
*   **Module Load Validation**: Automatic verification of field type definitions at runtime to prevent configuration corruption.

**Settings & Configuration**
*   **Config Sync**: Fully synchronized the Settings UI with `config.default.yaml`, exposing previously hidden parameters for Water Heating start penalties and gap tolerances.
*   **Today's Stats Integration**: Added a new "Today's Energy Sensors" section for mapping daily battery, PV, and grid totals directly to the Dashboard.
*   **Subscription Fees**: New setting for `Monthly subscription fee (SEK)` to improve long-term financial modeling.
*   **Vacation Mode**: Added formal configuration for Water Heater Vacation Mode, including anti-legionella safety cycles.
*   **Notification Rename**: Standardized notification naming (`on_export_start`, `on_water_heat_start`) to better reflect system states.
*   **Scheduler Toggle**: Added a master "Enable Background Scheduler" toggle for manual control over optimization cycles.

**Legacy Cleanup**
*   **Arbitrage Audit**: Identified and marked legacy arbitrage fields for investigation and potential removal.
*   **Consistency Fixes**: Fixed several naming discrepancies between the frontend form and backend config keys.

---

## [v2.4.8-beta] - Production-Grade Settings & Power Inversion - 2026-01-12

**Core Improvements**
*   **Robust Entity Validation**: Implemented type-aware validation in the Settings UI. Entering Home Assistant entity IDs (like `sensor.battery_soc`) no longer triggers "Must be a number" errors.
*   **Expanded Entity Filtering**: Updated Home Assistant discovery to include `select.`, `input_select.`, and `number.` domains. You can now correctly select work mode and other control entities in the dropdowns.
*   **Inline Power Inversion**: Added a sleek **± (Invert)** button directly next to `Grid Power` and `Battery Power` entity selectors. This allows for instant correction of inverted sensor readings.

**System & UX**
*   **System Inversion Support**: Both the instantaneous status API and the real-time WebSocket dashboard now respect the grid/battery power inversion flags.
*   **Persistence Layer Hardening**: Automatic retrieval and saving of "companion keys" ensures inversion settings persist even after UI reloads.
*   **CI & Linting**: Zero-error release prep with full Ruff and ESLint verification across the entire stack.

---

## [v2.4.7-beta] - Onboarding Documentation & UI Improvements - 2026-01-12

**Documentation & Guidance**
*   **New User Manual**: Launched `docs/USER_MANUAL.md`—a 48-hour guide to mastering Darkstar's UI, risk strategies, and troubleshooting.
*   **Refactored Setup Guide**: Rewrote `docs/SETUP_GUIDE.md` to be UI-first, including a **Hardware Cheat Sheet** for Solis/Deye/Huawei inverters.
*   **Safety Hardening**: Added critical "Watts vs kW" validation warnings to prevent common configuration errors.

**UI & Experience**
*   **Terminology Alignment**: Renamed "**Market Strategy**" to "**Risk Appetite**" across the entire UI and documentation for better conceptual clarity.
*   **Quick Actions Upgrade**: Refactored the Executor panel with real-time status banners and SoC targeting for force-charging.
*   **Settings Expansion**: Exposed previously "hidden" `config.yaml` sectors in the UI, including Water Heater temperature floors, PV confidence margins, and battery cycle costs.

**System Hardening**
*   **HA Status**: Improved Home Assistant connection indicators in the Sidebar (Green/Red/Grey states).
*   **Shadow Mode**: Formalized "Shadow Mode" documentation to help new users test safely before going live.
