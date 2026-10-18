## MODIFIED Requirements

### Requirement: EV tab shows read-only progress and status
The EV tab SHALL display the following per charger:
- a progress bar and percent computed as current SoC divided by the target SoC (clamped 0-100%) for chargers with a SoC sensor, and as delivered kWh divided by required kWh (clamped 0-100%) for chargers without one; the bar SHALL never show 100% from missing data;
- "Delivered Today" as an informational kWh value that does not drive the progress bar for chargers with SoC;
- a status badge (`on_track` / `behind` / `complete` / `idle` / `paused_by_load_balancer`);
- a planned per-day estimate from `planned_by_day`: one chip per day from today through the deadline day, showing the planned kWh.

Chips with `basis: "known"` SHALL render solid. Chips with `basis: "estimated"` SHALL render visually de-emphasised with an "est." label and a tooltip explaining that the value is based on forecast prices. Today's chip SHALL be highlighted. The section title SHALL read "Planned per day", not "Upcoming Daily Quotas".

#### Scenario: On-track goal
- **WHEN** the charger is progressing toward its target within the deadline
- **THEN** the badge SHALL read "On track" and the progress bar SHALL reflect SoC relative to target

#### Scenario: Delivered exceeds remaining need
- **WHEN** Delivered Today is 22 kWh but SoC is 50% with an 80% target
- **THEN** the progress SHALL be below 100% and consistent with the remaining need

#### Scenario: Goal complete
- **WHEN** SoC is at or above target
- **THEN** the badge SHALL read "Complete" and progress SHALL be 100%, without showing a "Target 0.0 kWh (0% of goal)" label

#### Scenario: Behind
- **WHEN** the ready-by has passed (or is unreachable) with energy still required
- **THEN** the badge SHALL read "Behind" and SHALL show the remaining kWh

#### Scenario: Mixed known and estimated days
- **WHEN** `planned_by_day` has today `known` 0 kWh, tomorrow `known` 8 kWh, and D+2 `estimated` 14 kWh
- **THEN** three chips SHALL render; the first two solid and the third de-emphasised with "est."

#### Scenario: No goal or no plan
- **WHEN** `planned_by_day` is empty or absent
- **THEN** the per-day section SHALL be hidden
