# Darkstar Release Notes

## [v2.4.8-beta] - 2026-01-12

**Core Improvements**
*   **Robust Entity Validation**: Implemented type-aware validation in the Settings UI. Entering Home Assistant entity IDs (like `sensor.battery_soc`) no longer triggers "Must be a number" errors.
*   **Expanded Entity Filtering**: Updated Home Assistant discovery to include `select.`, `input_select.`, and `number.` domains. You can now correctly select work mode and other control entities in the dropdowns.
*   **Inline Power Inversion**: Added a sleek **± (Invert)** button directly next to `Grid Power` and `Battery Power` entity selectors. This allows for instant correction of inverted sensor readings.

**System & UX**
*   **System Inversion Support**: Both the instantaneous status API and the real-time WebSocket dashboard now respect the grid/battery power inversion flags.
*   **Persistence Layer Hardening**: Automatic retrieval and saving of "companion keys" ensures inversion settings persist even after UI reloads.
*   **CI & Linting**: Zero-error release prep with full Ruff and ESLint verification across the entire stack.

---

## [v2.4.7-beta] - 2026-01-12

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
