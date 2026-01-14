# Darkstar Release Notes

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
