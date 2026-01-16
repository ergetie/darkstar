## [v2.5.0] - Configuration & Compatibility - 2026-01-16

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
