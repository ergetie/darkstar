## ADDED Requirements

### Requirement: EV charge current is derived from nominal battery voltage

When the charger is controlled in Amps, the executor SHALL convert a planned charge power (kW) to an Ampere setpoint using the configured `nominal_voltage_v`, not the worst-case `min_voltage_v`. `min_voltage_v` SHALL be used only for safety limits, not for the kW→A conversion.

#### Scenario: kW→A conversion uses nominal voltage

- **WHEN** the charger is in Ampere-control mode and a slot plans `P` kW
- **THEN** the commanded current equals `(P × 1000) / nominal_voltage_v`
- **AND** `min_voltage_v` is not used in the conversion

#### Scenario: Safety limits still use the configured current bounds

- **WHEN** the converted current exceeds the configured charge-current limit
- **THEN** it is clamped to that limit, unchanged from current behavior

### Requirement: Boost-cancellation notification is delivered

When a water boost is cancelled because SoC dropped below the configured floor, the executor SHALL deliver the cancellation notification (awaiting the async send), not create and discard the coroutine.

#### Scenario: Low-SoC boost cancellation notifies the user

- **WHEN** a water boost is cancelled because SoC fell below `min_soc + 10%`
- **THEN** the cancellation notification is sent to the configured notifier
- **AND** no "coroutine was never awaited" runtime warning is produced

### Requirement: WebSocket broadcast failures are logged, not swallowed

The executor SHALL log (at debug or warning level) when a real-time error/status WebSocket broadcast fails, instead of silently passing. The underlying record SHALL still be persisted before the broadcast is attempted.

#### Scenario: WS emit failure is logged

- **WHEN** the WebSocket manager raises during a real-time error/status broadcast
- **THEN** the failure is logged
- **AND** the error/status record remains persisted (e.g. in `recent_errors`)

### Requirement: The dead force_export quick action is removed

The executor SHALL NOT expose the `force_export` quick action. Its override type, controller branch, and engine handler are removed because it had no UI caller and hardcoded the grid-export limit to 0 W (exporting nothing). Other quick actions are unaffected.

#### Scenario: force_export is not a supported quick action

- **WHEN** a `force_export` quick action is requested
- **THEN** the executor does not treat it as a known quick action

#### Scenario: force_charge remains available

- **WHEN** a `force_charge` quick action is requested
- **THEN** it is handled exactly as before
