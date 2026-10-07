## MODIFIED Requirements

The calibration requirements below govern verified results. The separate configured-loss estimate requirement is the only permitted fallback and never changes calibration eligibility or gates.

### Requirement: Calibration uses installation observations without changing operation
The system SHALL derive one installation-specific effective inverter/battery loss model from at most 30 days of completed, compatible trustworthy observations ending at the selected comparison end. It SHALL model `bus = pv + discharge - charge`, `grid_net = demand - (eta_out * bus if bus >= 0 else bus / eta_in)`, and `stored_next = stored + eta_charge * charge - discharge / eta_discharge`. Factors SHALL be fitted within [0.80, 1.00] at resolution 0.002. Calibration SHALL NOT assume that all PV/battery readings are AC, add an additional guessed PV loss, use another installation's constants, write configuration, change planner settings, or modify recorded observations or provenance. It SHALL interpret configured capacity as full capacity and SHALL NOT infer or write a replacement physical capacity to obtain a passing model.

#### Scenario: Different sensor boundaries
- **WHEN** two installations record different effective PV-to-load conversion losses
- **THEN** each installation uses independently validated effective factors
- **AND** no additional universal PV derating is applied

#### Scenario: Unsupported measurements
- **WHEN** no model in the allowed family explains an installation within the validation gates
- **THEN** the comparison is unavailable with `unreliable_model`
- **AND** metered information remains available

#### Scenario: Full capacity is installation-specific
- **WHEN** users configure different full battery capacities
- **THEN** each SoC-to-energy conversion uses that installation's value and existing charge limits
- **AND** calibration does not use a shared installation constant

### Requirement: Calibration validates independent observations and sufficient excitation
Calibration SHALL reject null/non-finite/negative essential energy readings, invalid SoC/timestamps, rows marked `exclude: true`, known backfills and unsupported provenance. Legacy source metadata SHALL be eligible only with valid evidence-backed comparison-history attestation of a compatible measured-energy regime. Battery samples SHALL use only contiguous same-cohort 15-minute SoC pairs strictly within 10–95% SoC with battery throughput at least 0.05 kWh and independently trusted SoC. The system SHALL require at least 1,000 eligible grid observations and 200 eligible battery pairs, sorted in UTC and split chronologically 80% training and 20% validation. Both bus directions and both battery flow directions SHALL each have at least 30 training observations and 3 kWh of excitation; unidentifiable fits SHALL be rejected.

The withheld grid and battery fits SHALL each satisfy RMSE <= 0.25 kWh/sample and absolute mean error <= 0.03 kWh/sample. Grid net-cost error SHALL be <= max(1 kr, 5% of recorded gross billing volume), with billing volume computed using absolute prices and gross energies. The selected comparison period SHALL independently satisfy the grid energy/cost gates and trustworthy same-cohort coverage, including its initial SoC anchor. Fitting SHALL NOT use withheld samples or observations after the comparison end. These gates SHALL be described as reliability policy, not statistical confidence intervals.

#### Scenario: Too little history
- **WHEN** the installation has fewer than 1,000 eligible grid observations or 200 battery pairs in the selected compatible cohort
- **THEN** verified comparison amounts are withheld with `insufficient_data`

#### Scenario: Unobserved conversion direction
- **WHEN** training data lacks sufficient grid-charging bus excitation
- **THEN** the fit is rejected rather than assigning an invented learned input efficiency

#### Scenario: Withheld errors fail
- **WHEN** training errors are small but withheld net-cost error exceeds the gate
- **THEN** verified comparison amounts are withheld with `unreliable_model`

#### Scenario: Historical regime differs
- **WHEN** calibration passes holdout validation but fails selected-period validation or the period includes incompatible or unsupported measurements
- **THEN** that selected period has no verified comparison

#### Scenario: Negative prices and almost-zero net costs
- **WHEN** recorded prices include negative values or the net bill is near zero
- **THEN** the cost-error gate uses absolute-price gross billing volume rather than dividing by the net bill

#### Scenario: Unknown legacy history
- **WHEN** a legacy row has only `source: recorder`, missing metadata or an unsupported provenance version
- **THEN** it is excluded unless valid legacy attestation establishes compatibility
- **AND** a good numerical fit alone does not certify it

#### Scenario: Unsupported initial state
- **WHEN** the previous-slot SoC is cached, unverified, non-contiguous or from another boundary
- **THEN** it is not used to invent a trusted comparison start state

### Requirement: Calibration work is bounded and does not block async requests
The system SHALL perform calibration outside the async event-loop thread and SHALL use a bounded in-memory cache with at most a 15-minute lifetime. Cache identity SHALL include installation/database identity, relevant battery/sensor configuration, model version, latest completed observation, selected cohort identity and a canonical digest of comparison-relevant provenance within the candidate window. Configuration changes or metadata-only annotation/rollback SHALL invalidate cached fits. Cached data SHALL NOT introduce observations later than the comparison end, and calibration SHALL require no new persistent schema or dependency.

#### Scenario: Configuration changes
- **WHEN** capacity or relevant measurement configuration changes
- **THEN** a previously cached fit is not reused

#### Scenario: Concurrent energy request
- **WHEN** a cache miss starts fitting
- **THEN** numerical fitting does not run on the async event-loop thread

#### Scenario: Metadata-only change under WAL
- **WHEN** historical provenance changes without changing the latest slot or main database file identity/mtime
- **THEN** the prior cached fit is invalidated by the provenance digest

## ADDED Requirements

### Requirement: Compatible cohort selection precedes numerical fitting
Calibration SHALL select the latest trustworthy completed measurement cohort compatible with the current installation boundary before inspecting fit outcomes. Cohorts SHALL distinguish supported energy semantics and measurement-boundary mappings. Snapshot or mixed essential energy, cached SoC, unknown provenance and enabled but unconfigured essential inputs SHALL NOT qualify; legitimately disabled zero components SHALL qualify. Historical measured methods SHALL share a cohort only through explicit supported compatibility and evidence-backed attestation. Snapshot outages SHALL NOT reset the cohort or allow an older incompatible fallback. Cohort selection SHALL NOT search date cutoffs or regimes for a passing result and SHALL NOT contain installation-specific dates or sizes.

#### Scenario: Recording method changed
- **WHEN** old snapshot-based and newer verified measured-energy observations coexist
- **THEN** snapshot observations are excluded before training/validation selection
- **AND** the current measured cohort is not inflated with old samples

#### Scenario: Current cohort too small
- **WHEN** an older incompatible cohort has sufficient samples but the current one does not
- **THEN** status is `insufficient_data` with a provenance-specific reason and no verified comparison amounts

#### Scenario: Configuration changes the measurement boundary
- **WHEN** meter topology, energy entity mapping or sign/load-isolation semantics change
- **THEN** incompatible old observations do not join the new boundary cohort

#### Scenario: Compatible semantic version
- **WHEN** an app release leaves supported recording semantics and sensor boundary unchanged
- **THEN** the app version alone does not discard compatible history

#### Scenario: Fallback during a completed period
- **WHEN** a selected period contains a known snapshot fallback despite a valid fitted model
- **THEN** the comparison is unavailable for that period rather than silently omitting the slot

### Requirement: Immediate configured-loss estimates remain distinct from verified calibration
The system SHALL provide a separate `estimated` result for a complete valid selected period when strict calibration is unavailable or rejected. Its grid basis SHALL be the planner AC-bus convention (`GridModel(1, 1)`); its storage basis SHALL use configured charge/discharge efficiencies, configured full capacity, and configured SoC/power limits. Both recorded Darkstar actions and self-use SHALL be reconstructed using that same model. The result SHALL expose `basis: configured_losses`, explicitly identify itself as an estimate, and preserve the actual calibration status/reason without fabricated fit diagnostics or validation results. A strict model that passes all existing cohort, sample, excitation, holdout and selected-period gates SHALL automatically replace the estimate with `status: available` and `basis: calibrated`; verification SHALL mean that the model passed those checks, not that counterfactual cash flow is exact. Actual metered cash flow SHALL remain separate and unchanged.

Estimate eligibility SHALL require contiguous completed slots, finite nonnegative essential energies, finite prices, valid configured capacity/limits/efficiencies, and a valid independent start and end SoC state. A valid contiguous preceding end SoC may supply a missing start anchor. Explicit exclusions, backfills, known snapshot/mixed essential provenance, cached SoC and unsupported modern provenance SHALL remain rejected. Legacy recorder rows with unknown provenance may be used only as explicitly assumed estimate inputs, including an existing contiguous end-SoC anchor; they SHALL remain ineligible for calibration and SHALL NOT receive attestation. The registered initial schema-v1 boundary encoding that omitted the SoC entity MAY be an explicit estimate assumption only when the fingerprint equals the current boundary with that single field omitted and every other method/identity and live endpoint is supported. It SHALL remain ineligible for strict calibration; arbitrary boundary changes and unsupported algorithms SHALL remain rejected. Bounded assumption counts SHALL distinguish legacy recording and uncertain historical SoC mapping. Missing values SHALL NOT be invented. Failed numeric calibration SHALL retain its actual failure reason while a valid estimate is shown.

#### Scenario: Usable legacy period before calibration
- **WHEN** a complete selected period has valid legacy recorder values but no compatible calibration cohort
- **THEN** the response returns configured-loss estimate amounts immediately with an explicit assumed basis
- **AND** calibration remains `insufficient_data` with its original history reason and no fabricated diagnostics

#### Scenario: Verified model becomes available
- **WHEN** the compatible cohort later passes all existing calibration and selected-period checks
- **THEN** the comparison automatically uses calibrated factors and is labelled verified
- **AND** its economics use the same shared arithmetic as the estimate

#### Scenario: Unsupported provenance stays rejected
- **WHEN** a period contains a known snapshot, backfill, cached SoC, exclusion, unsupported modern provenance, or required missing value
- **THEN** no configured-loss amounts are returned for that period

#### Scenario: Invalid estimate inputs
- **WHEN** prices, energies, capacity, limits, configured efficiencies, or required SoC anchors are missing, non-finite, or outside valid bounds
- **THEN** no comparison amounts are returned

#### Scenario: Estimate does not certify history
- **WHEN** an estimate uses unknown legacy recorder provenance
- **THEN** those rows remain excluded from calibration and receive no provenance attestation

#### Scenario: Earlier SoC boundary encoding
- **WHEN** a supported measured recorder row uses the initial fingerprint encoding that omitted only the SoC sensor mapping and all other configured paths match
- **THEN** the estimate may use it with an explicit SoC-mapping assumption count
- **AND** strict calibration still rejects it, historical metadata is unchanged, and a changed unrelated sensor or unsupported algorithm is not accepted
