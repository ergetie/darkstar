## ADDED Requirements

### Requirement: Unmeasured device or load components make a slot partial, not excluded
A slot SHALL be included in the grid-only comparison when its import and export (and battery charge and discharge when a battery is present) are measured with recorder provenance, whatever the method of its device and load components. If any device component (`ev`, `water`, any other device component) has method `unknown` or `unconfigured_zero`, or any of those or `load` has method `snapshot` or `mixed`, the slot SHALL be included and marked partial with the reason `unmeasured_component` (or `unconfigured_sensor` for `unconfigured_zero`) and the component name. A slot SHALL stay excluded when import, export, or battery flows (when a battery is present) are not measured, when `load` is `unknown` or `unconfigured_zero`, or for the existing integrity reasons.

#### Scenario: EV unknown, grid flows measured
- **WHEN** a slot has `ev=unknown`, `load=derived_history`, and measured import and export
- **THEN** the slot is included, marked partial for `ev`, and the cumulative lines stay continuous

#### Scenario: Snapshot or mixed device or load
- **WHEN** a slot has `ev=snapshot` and `load=mixed` with measured import and export
- **THEN** the slot is included and marked partial

#### Scenario: Mixed load caused by a partial device
- **WHEN** a slot has `load=mixed` and a device component (for example `ev=snapshot`) that is itself partial
- **THEN** the slot has a partial entry for the device only and none for `load`; a `load=snapshot` slot, or a `load=mixed` slot with no partial device, keeps its `load` partial entry

#### Scenario: Import missing
- **WHEN** import is not measured
- **THEN** the slot is excluded with reason `unknown_component` for `import`

#### Scenario: Load unknown
- **WHEN** `load` has method `unknown`
- **THEN** the slot is excluded because demand cannot be priced

#### Scenario: Device component absent from provenance
- **WHEN** the provenance has no entry for a device (for example no EV configured)
- **THEN** the slot is not excluded for it

#### Scenario: Guard
- **WHEN** any device component type is unknown, snapshot or mixed while import and export are measured
- **THEN** that component never causes the slot to be excluded

### Requirement: Hidden-demand clamp check covers every unknown device
The `clamp_hidden_demand` exclusion SHALL apply when any device component is unknown and the base-load clamp may have hidden demand (`load_kwh == 0` while another device energy is above 0).

#### Scenario: Both devices unknown with zero load
- **WHEN** `ev` and `water` are unknown and `load_kwh` is 0 with import above 0
- **THEN** the slot is excluded with reason `clamp_hidden_demand`

### Requirement: Coverage reports partial slots
The comparison coverage SHALL include `partial_slots`, `partial_hours` and `partial_by_component`, and the response SHALL include `partial_spans` with start, end, slots, reason and component, built like `excluded_spans`. `water_unmeasured_slots` and `water_unmeasured_hours` SHALL stay for compatibility and equal the `water` entry of `partial_by_component`. Partial slots count as covered. Comparison status stays `available`/`partial` by covered-versus-total coverage only; partial slots alone do not make it `partial`.

#### Scenario: Coverage counts
- **WHEN** 105 slots are partial for `ev`
- **THEN** `partial_slots` is 105, `partial_hours` is 26.25, `partial_by_component.ev` is 105, and `covered_slots` includes them
