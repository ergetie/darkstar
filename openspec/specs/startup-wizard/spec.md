# Capability: Startup Wizard

## Purpose
The Startup Wizard walks a fresh installation through selecting an inverter profile, entering equipment specifications, and configuring baseline consumption before the main dashboard becomes accessible.

## Requirements

### Requirement: Triggering the Setup Wizard

The system MUST detect when a fresh installation requires initial configuration and force the user into the Setup Wizard, preventing access to the main dashboard.

#### Scenario: Fresh Installation Detected
- **WHEN** the application loads
- **AND** `config.system.inverter_profile` is `null`
- **THEN** the user is redirected to the full-screen Startup Wizard
- **AND** the main dashboard route `/` is inaccessible

#### Scenario: Existing Installation Detected
- **WHEN** the application loads
- **AND** `config.system.inverter_profile` is a valid string (e.g., "generic", "deye")
- **THEN** the user is granted access to the main dashboard route `/`
- **AND** the Startup Wizard is not shown

### Requirement: Step 1 - Equipment Profile Selection

The user MUST be able to select their inverter hardware profile, which automatically populates the standard Home Assistant entities for that hardware.

#### Scenario: User selects a hardware profile
- **WHEN** the user is on Step 1 of the wizard
- **AND** the user clicks an inverter profile button (e.g., "Deye", "Fronius")
- **THEN** the wizard proceeds to Step 2
- **AND** the selected profile is temporarily stored in the wizard state

### Requirement: Step 2 - Equipment Specifications

The user MUST configure their basic energy hardware specifications so the system knows its physical limits.

#### Scenario: User enters hardware specifications
- **WHEN** the user is on Step 2 of the wizard
- **AND** the user enters a valid Battery Capacity (kWh) and Solar Array Peak Power (kWp)
- **THEN** the "Next" button becomes enabled
- **AND** clicking "Next" proceeds to Step 3 and stores the values in the wizard state

### Requirement: Step 3 - Baseline Consumption

The user MUST provide a baseline consumption source, either by selecting an existing Home Assistant historical sensor or by estimating their daily usage for a synthetic profile.

#### Scenario: User selects a Home Assistant sensor
- **WHEN** the user is on Step 3 of the wizard
- **AND** the user selects a valid `total_load_consumption` sensor
- **THEN** the system triggers an asynchronous 7-day data fetch of the selected sensor
- **AND** the configuration is finalized

#### Scenario: User estimates daily usage
- **WHEN** the user is on Step 3 of the wizard
- **AND** the user chooses to estimate usage instead of selecting a sensor
- **AND** the user inputs an "Estimated Daily kWh" value
- **THEN** the backend generates a "Synthetic Heat Pump Profile" scaled to the input kWh value
- **AND** the configuration is finalized

### Requirement: Finalizing Configuration

The system MUST save the collected configuration, validate it, and reload the backend engine to apply the changes.

#### Scenario: User completes the wizard
- **WHEN** the configuration is finalized on Step 3
- **THEN** the UI sends a save request to the backend with the collected `inverter_profile`, `battery.capacity_kwh`, `system.solar_arrays[0].kwp`, and the baseline consumption settings
- **AND** the backend validates the configuration and saves it to `config.yaml`
- **AND** the backend triggers an `ExecutorEngine` reload
- **AND** the user is redirected to the main dashboard `/`
