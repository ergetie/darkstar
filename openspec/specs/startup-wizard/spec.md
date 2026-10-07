# Capability: Startup Wizard

## Purpose
The Startup Wizard guides users through connecting Darkstar and configuring their energy system, then provides a readiness review. Users can skip or dismiss setup and return to it from Settings.
## Requirements
### Requirement: Triggering the Setup Wizard

The system MUST open the onboarding wizard automatically on a fresh installation, MUST allow the user to skip or close it at any time, and MUST allow re-opening it later. The dashboard MUST remain accessible after the wizard is skipped.

#### Scenario: Fresh Installation Detected
- **WHEN** the application loads
- **AND** `config.system.inverter_profile` is `null`
- **AND** the onboarding status is `not_started` or `in_progress`
- **THEN** the onboarding wizard is shown, resumed at the persisted `current_step` if any

#### Scenario: Existing Installation Detected
- **WHEN** the application loads
- **AND** `config.system.inverter_profile` is a valid string
- **THEN** the wizard is not shown automatically

#### Scenario: User skips onboarding
- **WHEN** the user clicks "Skip setup" and confirms
- **THEN** the onboarding status is set to `dismissed`
- **AND** the saved configuration, `current_step` and `completed_steps` are preserved
- **AND** the dashboard is accessible
- **AND** the wizard does not auto-open on next load

#### Scenario: User closes onboarding
- **WHEN** the user clicks the X close action and confirms
- **THEN** the onboarding status is set to `dismissed`
- **AND** the saved configuration, `current_step` and `completed_steps` are preserved
- **AND** the dashboard is accessible
- **AND** the wizard does not auto-open on next load

#### Scenario: Re-run from Settings
- **WHEN** the user clicks "Run setup again" in Settings
- **THEN** the wizard opens with every field pre-filled from the current configuration
- **AND** it resumes at the saved `current_step` when one exists
- **AND** the onboarding status changes to `in_progress`

### Requirement: Missing-profile state reflects the saved config
The UI's missing-inverter-profile state (wizard trigger and "inverter profile not set" banner) SHALL be re-evaluated from freshly fetched config after the wizard completes and after any successful settings save, not only on initial page load.

#### Scenario: Banner clears after wizard completes
- **WHEN** a fresh install completes the wizard with profile `deye`
- **THEN** the "inverter profile not set" banner SHALL NOT be shown
- **AND** no page reload SHALL be required

#### Scenario: Banner clears after profile set in Settings
- **WHEN** the banner is shown and the user saves a non-null inverter profile in Settings
- **THEN** the banner SHALL disappear after the save succeeds

### Requirement: Conditional step flow
The wizard SHALL present the steps Connect, My system, Location & pricing, Inverter, Core sensors, Solar, Battery, Water heater, EV, Review & readiness, omitting Solar, Battery, Water heater and EV when the corresponding `has_*` flag is false. Progress indication SHALL count only applicable steps.

#### Scenario: No EV, no water heater
- **WHEN** the user disables water heater and EV in My system
- **THEN** the Water heater and EV steps are not shown and progress counts 8 steps

### Requirement: Connect step
In add-on mode the step SHALL verify the Supervisor connection automatically. In standalone mode the user SHALL enter URL and token, which SHALL be tested as typed and saved only after a successful test.

#### Scenario: Standalone first run
- **WHEN** a standalone user enters valid URL and token and clicks Test
- **THEN** the test succeeds using the typed values and the credentials are saved

### Requirement: System definition step
The user SHALL define has solar, has battery, has water heater, has EV, grid meter type and grid import limit (with a fuse amps × phases helper) before hardware steps.

#### Scenario: Fuse helper
- **WHEN** the user enters 20 A and 3 phases
- **THEN** `system.grid.max_power_kw` is pre-filled with approximately 13.8

### Requirement: Location and pricing step
The step SHALL pre-fill latitude, longitude, timezone and currency from HA core config, require an explicit Nordpool area choice (SE1–SE4, each with a region description, keeping the existing value on re-run and preselecting none on fresh installs), and collect VAT, energy tax and flat transfer fee with Swedish defaults.

#### Scenario: Auto-filled location
- **WHEN** HA core config is available and the config still has placeholder coordinates
- **THEN** the HA coordinates and timezone are pre-filled and marked auto-detected

### Requirement: Inverter step
The brand dropdown SHALL list exactly the profiles returned by `GET /api/profiles`, pre-select the suggested brand, and show each required profile entity as an entity field with suggestions.

#### Scenario: Profile list is dynamic
- **WHEN** the backend returns profiles `deye, fronius, generic, sungrow`
- **THEN** the dropdown shows exactly those four and no others

### Requirement: Entity fields show live values and confidence
Every entity picker in the wizard SHALL show the selected entity's live state and unit, a confidence badge for suggestions, and a plausibility hint for the role. Empty fields SHALL be pre-filled only by high-confidence suggestions.

#### Scenario: Medium confidence not pre-filled
- **WHEN** the best candidate for an empty field is medium confidence
- **THEN** the field stays empty and the candidate is offered as a suggestion

### Requirement: Never overwrite silently
When a field already has a configured value, the wizard SHALL keep it selected and SHALL offer any differing suggestion only as an explicit action. The Review step SHALL list all values changed during the session as current → new.

#### Scenario: Re-run with differing suggestion
- **WHEN** `executor.inverter.work_mode` is configured and the suggestion differs
- **THEN** the configured value remains selected
- **AND** a "use suggested" action is shown
- **AND** nothing is changed unless the user applies it

### Requirement: Core sensors step
The step SHALL collect `load_power`; `grid_power` or `grid_import_power`/`grid_export_power` per meter type; `battery_soc` and `battery_power` when battery; `pv_power` when solar; and an optional synthetic daily kWh saved to `input_sensors.synthetic_daily_load_kwh`. The step SHALL NOT collect cumulative energy counters or offer a choice between a counter and an estimate. Step completion SHALL depend only on the required power sensors, not on the synthetic value.

#### Scenario: Synthetic baseline saved
- **WHEN** the user enters 20 kWh/day in the optional estimated daily use field
- **THEN** `input_sensors.synthetic_daily_load_kwh` is saved as 20

#### Scenario: Step completes without synthetic value
- **WHEN** all required power sensors for the system are set and the synthetic field is empty
- **THEN** the step is complete

#### Scenario: No counter fields or suggestions
- **WHEN** the step is shown
- **THEN** no `total_*` field is displayed and no `total_*` role is requested from `/api/setup/suggestions`

### Requirement: Solar and battery steps
The Solar step SHALL collect one or more arrays with name, kWp, tilt and azimuth. The Battery step SHALL collect capacity, min/max SoC and max charge/discharge power in W, and SHALL NOT allow continuing with zero charge/discharge power.

#### Scenario: Missing battery power
- **WHEN** max charge power is empty
- **THEN** Next is disabled with an explanation

### Requirement: Water heater and EV steps
The Water heater step SHALL collect name, control entity, power sensor, power_kw and type. The EV step SHALL collect charger name and type, control entities, car SoC and plug sensors, battery capacity, and rated power (binary) or min/max current and phases (current type). Entries SHALL pass backend save validation before continuing.

#### Scenario: Current-type EV without current entity
- **WHEN** type is current and no current entity is selected
- **THEN** the save validation error is shown inline and Next is blocked

### Requirement: Per-step save and resume
Completing a step SHALL save that step's patch via the config save endpoint and record progress in the onboarding state. Closing with X or skipping SHALL preserve the saved configuration, `current_step` and `completed_steps`. A dismissed wizard SHALL resume at the saved step when opened manually from Settings. If the application exits while onboarding remains `in_progress`, it SHALL auto-open at the persisted step on the next load. Back navigation SHALL allow editing any earlier applicable step.

#### Scenario: Resume after interruption
- **WHEN** the user completes Pricing and reopens Darkstar while onboarding remains `in_progress`
- **THEN** the wizard opens at Inverter with pricing values retained

#### Scenario: Resume after dismissal
- **WHEN** the user dismisses the wizard at Inverter and later opens it from Settings
- **THEN** the wizard resumes at Inverter with pricing values retained

#### Scenario: Validation blocks
- **WHEN** a step's save returns HTTP 400
- **THEN** the errors are shown inline and the wizard stays on that step

### Requirement: Readiness review
The final step SHALL display the readiness checks with status and fix hints, each linking to the step that owns the setting. While the batch readiness request is running, the UI SHALL show a truthful checking state; after it completes, it SHALL show pass, warning, failure and skipped totals. Remediation text SHALL appear only for warning or failed checks and SHALL use units appropriate to the sensor role. The user SHALL be able to finish while checks fail, with a clear notice that Darkstar will not work until they are resolved.

#### Scenario: Fix link
- **WHEN** the battery_soc check fails and the user clicks Fix
- **THEN** the wizard navigates to the Core sensors step

#### Scenario: Readiness request is in progress
- **WHEN** the review step starts its readiness request
- **THEN** it shows "Checking readiness…" until the single batch response arrives
- **AND** it shows the returned status totals without inventing per-check progress

#### Scenario: Battery SoC remediation
- **WHEN** a battery_soc check warns or fails
- **THEN** its remediation says to use a battery state-of-charge sensor reporting 0–100 %
- **AND** a passing battery_soc check has no remediation text

### Requirement: Shadow mode finish
Finishing SHALL leave `executor.shadow_mode` true (unless a re-run finds it already false, which is kept and shown), set onboarding status `completed`, and explain that Darkstar plans without controlling hardware until shadow mode is turned off in Settings. A "Go live now" action SHALL set `shadow_mode` false after confirmation and SHALL be disabled while any readiness check fails. The wizard SHALL NOT trigger an executor run.

#### Scenario: Default finish
- **WHEN** the user clicks Finish on a fresh install
- **THEN** `executor.shadow_mode` is true and the shadow-mode explanation is shown
- **AND** no executor run is triggered

#### Scenario: Go live
- **WHEN** readiness is all pass/warn and the user confirms "Go live now"
- **THEN** `executor.shadow_mode` is saved as false

### Requirement: Installation statistics choice in final review
The final Review & readiness step SHALL include a clearly labeled installation-statistics toggle initialized from effective `installation_stats.enabled`, enabled when absent. Concise helper text SHALL disclose the daily random installation ID, version, release channel, installation type, CPU architecture, and inverter profile reporting, with custom profile names excluded. The final save SHALL persist this choice before marking onboarding complete. This control SHALL NOT add a wizard step, affect readiness results, trigger execution, force existing users through onboarding, or create an upgrade notice. A rerun SHALL preserve and display the saved choice.

#### Scenario: Fresh installation finishes with default reporting
- **WHEN** a new installation reaches Review & readiness and finishes without changing the statistics toggle
- **THEN** the toggle is enabled and reporting remains enabled
- **AND** existing shadow-mode and go-live completion behavior is preserved

#### Scenario: Disable reporting before finishing
- **WHEN** a user turns the final-review toggle off and successfully finishes
- **THEN** `installation_stats.enabled` is saved as false before onboarding is marked completed
- **AND** the sender re-evaluates the saved choice and dispatches no subsequent heartbeat

#### Scenario: Rerun or save failure
- **WHEN** a user reruns onboarding after disabling reporting
- **THEN** the toggle starts disabled and is not silently re-enabled
- **AND** a failed final save keeps onboarding incomplete and displays the existing save error
