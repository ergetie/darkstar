## ADDED Requirements

### Requirement: Reported plan cost uses the effective export price

The reported plan cost (`total_cost_sek` and per-slot `cost_sek`) SHALL be recomputed using the same effective export price the solver objective minimized — `export_price − export_threshold` per exported kWh — so the displayed cost matches the optimized quantity. This is a reporting correction only; planning decisions are unchanged.

#### Scenario: Reported cost matches the optimized export price

- **WHEN** a plan exports energy in slots with a non-zero export threshold
- **THEN** the reported cost values the exported energy at `export_price − export_threshold` per kWh
- **AND** the reported total equals the cost the solver actually minimized

#### Scenario: No double-subtraction and no decision change

- **WHEN** the export threshold is zero
- **THEN** the reported cost is identical to today's value
- **AND** the chosen schedule is unchanged in all cases

### Requirement: Simulation SoC projection reflects total battery charge within the SoC band

The `/api/simulate` SoC projection SHALL use total battery charge (including PV-sourced charge), not grid-sourced charge only, and SHALL clamp the projected SoC to the configured min/max SoC band.

#### Scenario: PV charging is reflected in the simulated SoC curve

- **WHEN** the battery charges from surplus PV in a simulated slot
- **THEN** the projected SoC rises by the total battery charge for that slot, not only the grid-sourced portion

#### Scenario: Projected SoC stays within the configured band

- **WHEN** the projection would exceed the configured min or max SoC
- **THEN** the projected SoC is clamped to the configured band
