## ADDED Requirements

### Requirement: Config reload reaches the action dispatcher
When `reload_config()` loads a changed config, the new `ExecutorConfig` SHALL be applied to the `ActionDispatcher` at the start of the next tick, without restart. Each tick SHALL snapshot the config once and the dispatcher SHALL use only that snapshot for the whole tick, even if a reload from another thread completes mid-tick.

#### Scenario: soc_target entity changed in Settings
- **GIVEN** the executor runs with `executor.inverter.soc_target: input_number.master_soc_target`
- **WHEN** the config is saved with `soc_target: number.inverter_program_6_soc` and `reload_config()` runs
- **THEN** the next SoC target write goes to `number.inverter_program_6_soc`
- **AND** no write goes to `input_number.master_soc_target`

#### Scenario: Unchanged config
- **WHEN** `reload_config()` runs and config and profile mtimes are unchanged
- **THEN** the dispatcher config object is not replaced

#### Scenario: Reload during a tick
- **GIVEN** a tick is executing with `soc_target: input_number.master_soc_target`
- **WHEN** an API thread calls `reload_config()` with `soc_target: number.inverter_program_6_soc` before the tick's SoC write
- **THEN** that tick writes only `input_number.master_soc_target`
- **AND** the next tick writes `number.inverter_program_6_soc`
