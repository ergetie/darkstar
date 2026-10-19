## ADDED Requirements

### Requirement: Deye soc_target defaults to program 6 SoC
The Deye profile SHALL default `soc_target` to `number.inverter_program_6_soc` and its match rules SHALL accept `number` and `input_number` domains, ranking a program 6 SoC entity above a `soc_target` helper. Program 1-5 SoC entities SHALL NOT match. Any user-chosen entity SHALL remain accepted.

#### Scenario: Auto-detect finds program 6
- **GIVEN** HA has `number.inverter_program_1_soc` ... `number.inverter_program_6_soc` (Solarman, unit %)
- **WHEN** entity suggestions run for the Deye profile
- **THEN** the top `soc_target` candidate is `number.inverter_program_6_soc`

#### Scenario: Helper setup still valid
- **GIVEN** a config with `soc_target: input_number.master_soc_target`
- **WHEN** the config is loaded and validated
- **THEN** no error is raised and the executor writes the helper
