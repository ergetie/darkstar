## ADDED Requirements

### Requirement: EV Charging guide describes the current EV system
The EV Charging guide SHALL be a complete, plain-language description of the current EV behaviour, with every statement matching the code. It SHALL cover, in scannable numbered sections:
- charger setup: current chargers (amps × phases × `system.grid.nominal_voltage_v` derive power), binary chargers (`rated_power_kw`), the missing-phases prompt, and the plug sensor;
- goals: one-off and repeating (daily, weekdays, weekends, every N days), a Home Assistant ready-by change always creating a one-off goal, and keep-on after target;
- planning: direct optimisation on published prices, deferral pricing beyond them at the published or forecast price plus a risk margin ramping from the base to the deadline value, the shortfall penalty, and the known/estimated planned-per-day chips;
- solar surplus: battery first, then the Excess PV sink priority order with overflow to the next sink, surplus counting toward the goal;
- replanning: on goal save or HA change (with the "Re-planning" state), plug-in/unplug, SoC recovery, planning while unplugged, and the global plug-in reminder;
- stale SoC behaviour; the EV cost sub-row under Grid Import;
- load balancing: 85 % target margin, instant amp reduction, 1-phase relief, pause after the 5 s delay, immediate pause above 125 %, 60 s averaged ramp-up, and dwell;
- phase switching setup, with a go-e example (`select.<charger>_psm`, options `one_phase` / `three_phases`, 1-phase line L1) and the rule that `binary_sensor` entities cannot be used.

The guide SHALL reference its related settings fields, and every referenced field SHALL exist in the search index.

#### Scenario: Guide found by everyday words
- **WHEN** the user searches "phase switching" or "plug-in reminder"
- **THEN** the EV Charging guide SHALL be among the guide results

#### Scenario: Related fields resolve
- **WHEN** the guide's related fields are listed
- **THEN** each SHALL exist in the settings field index
