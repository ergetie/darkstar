## MODIFIED Requirements

### Requirement: Inverter AC constraint permits zero discharge when PV forecast exceeds inverter capacity
The Kepler MILP SHALL apply the `max_inverter_ac_kw` limit only to power that crosses the AC inverter. It SHALL split forecast PV per slot into `pv_to_battery[t] >= 0` (DC-coupled charge that bypasses the AC stage) and `pv_to_ac[t] >= 0` (PV feeding load/export through the inverter), with the balance `pv_to_battery[t] + pv_to_ac[t] + curtailment[t] == s.pv_kwh` where `s.pv_kwh = pv_forecast[t]`. The AC limit SHALL be enforced as `pv_to_ac[t] + discharge[t] <= inverter_ac_kwh` where `inverter_ac_kwh = max_inverter_ac_kw * slot_hours[t]`.

For `dc_coupled` topology (the default), `pv_to_battery[t]` SHALL NOT count against the AC limit and SHALL be bounded only by available battery charge headroom and the battery charge-power limit. For `ac_coupled` topology, battery charging also crosses the AC inverter and the limit SHALL include it (equivalent to the previous `pv_forecast[t] + discharge[t] <= inverter_ac_kwh`).

The model SHALL remain feasible for every `pv_forecast[t]`, including `pv_forecast[t] >= inverter_ac_kwh`: surplus PV that cannot cross the AC side SHALL be absorbable by `pv_to_battery[t]` (subject to battery headroom) or `curtailment[t]`, never forcing infeasibility. When `max_inverter_ac_kw` is unset, no AC-limit constraint SHALL be added (unchanged default).

#### Scenario: PV forecast within inverter limit — normal discharge bound (dc_coupled)
- **WHEN** `pv_forecast[t] = 1.5 kWh`, `inverter_ac_kwh = 2.0 kWh`, topology `dc_coupled`, and no PV is routed to battery (`pv_to_battery[t] = 0`)
- **THEN** `pv_to_ac[t] = 1.5 kWh` and `discharge[t] <= 0.5 kWh`
- **AND** the LP is feasible for this slot

#### Scenario: PV forecast exceeds inverter limit — surplus routes to battery, no infeasibility (dc_coupled)
- **WHEN** `pv_forecast[t] = 2.1177 kWh`, `inverter_ac_kwh = 2.0 kWh`, topology `dc_coupled`, and battery charge headroom is available
- **THEN** the surplus above `inverter_ac_kwh` SHALL be absorbable by `pv_to_battery[t]` (here `pv_to_battery[t] >= 0.1177 kWh`) rather than forced to curtailment
- **AND** `pv_to_ac[t] + discharge[t] <= 2.0 kWh` holds
- **AND** the solver returns `Optimal`, not `Infeasible`

#### Scenario: PV-to-AC export is independently capped (dc_coupled)
- **WHEN** `pv_forecast[t] = 3.0 kWh`, `inverter_ac_kwh = 2.0 kWh`, topology `dc_coupled`, and battery headroom can absorb 1.0 kWh
- **THEN** `pv_to_ac[t] <= 2.0 kWh` (so PV feeding load + export never exceeds the AC rating)
- **AND** the remaining `>= 1.0 kWh` is routed to `pv_to_battery[t]` and/or `curtailment[t]`
- **AND** the plan SHALL NOT assume grid export of PV beyond `inverter_ac_kwh` in this slot

#### Scenario: AC-coupled topology retains the stricter combined limit
- **WHEN** `pv_forecast[t] = 1.5 kWh`, `inverter_ac_kwh = 2.0 kWh`, and topology `ac_coupled`
- **THEN** battery charging counts against the AC limit, enforcing `pv_forecast[t] + discharge[t] <= inverter_ac_kwh` (i.e. `discharge[t] <= 0.5 kWh`)
- **AND** when `pv_forecast[t] >= inverter_ac_kwh` the effective discharge upper bound is `0.0` and the LP remains feasible

#### Scenario: Inverter limit unset — no AC constraint added
- **WHEN** `max_inverter_ac_kw` is unset (default)
- **THEN** no inverter-AC constraint SHALL be added to the MILP
- **AND** PV routing variables MAY be omitted (no AC cap to enforce)
