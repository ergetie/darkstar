# Spec: EV Goal Shortfall Diagnostics

## Purpose

TBD - created by syncing change fix-ev-current-charger-control. Covers per-charger EV goal shortfall diagnostics computed by the planner and surfaced to users.

## Requirements

### Requirement: Planner computes per-charger goal diagnostics
For each plugged-in charger with an active goal (required_kwh > 0 and a deadline), the planner SHALL compute `required_kwh`, `scheduled_kwh`, `shortfall_kwh` (from the solver's per-charger shortfall) and, when shortfall > 0.01 kWh, a `reason`:
- `deadline_too_close`: no slot starting at or after now ends at or before the deadline
- `grid_limit`: in every eligible slot, the grid import headroom (max import minus house load, water heating and other EV energy in that slot) is below the charger's minimum energy per slot
- `cost_tradeoff`: any other case

The diagnostics SHALL be persisted in schedule metadata as `ev_goal_diagnostics[charger_id]` together with the goal's deadline. The existing zero-scheduled WARNING SHALL include the reason.

#### Scenario: Grid limit blocks the only slots
- **WHEN** the goal needs 0.6 kWh by 18:30, the charger minimum is 4.14 kW, max import is 8 kW, and each eligible slot already has 3 kW water heating plus 1.4 kW house load
- **THEN** diagnostics SHALL report `scheduled_kwh=0`, `shortfall_kwh=0.6`, `reason="grid_limit"`

#### Scenario: Goal fully scheduled
- **WHEN** the solver schedules the full required energy
- **THEN** diagnostics SHALL report `shortfall_kwh=0` and no reason

### Requirement: EV API reports at-risk goals
The EV goal API SHALL report status `at_risk` when the current schedule's diagnostics for that charger show shortfall > 0.01 kWh and belong to the active goal (same deadline, required energy within 0.05 kWh). The response SHALL include `shortfall_kwh` and `shortfall_reason`. Otherwise the existing status rules SHALL apply.

#### Scenario: Stale diagnostics ignored
- **WHEN** the user changes the goal deadline and the schedule has not been replanned yet
- **THEN** the API SHALL NOT report `at_risk` based on the old diagnostics

### Requirement: EV card shows at-risk goals with the reason
The EV tab SHALL render an amber "AT RISK" status pill for `at_risk`, plus a plain-language line stating the undelivered kWh, the ready-by time and the reason (for example "grid limit (8 kW) leaves no room", "ready-by too close", "cheaper to miss than to charge"), using design-system tokens.

#### Scenario: At-risk display
- **WHEN** the API returns `status="at_risk"`, `shortfall_kwh=0.6`, `shortfall_reason="grid_limit"`
- **THEN** the card SHALL show "AT RISK" instead of "ON TRACK", together with the shortfall line
