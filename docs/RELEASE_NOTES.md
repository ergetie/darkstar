# Darkstar v2.4.7-beta Release Notes

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
