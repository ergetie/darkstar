## ADDED Requirements

### Requirement: Actual measurement provenance accompanies recorded values
The recorder SHALL persist versioned per-component measurement provenance and writer ownership, measurement-boundary fingerprint, supported energy-semantics identifier and SoC source/ownership in existing `quality_flags`. It SHALL distinguish integrated power history, snapshot estimates, disabled zeros, unconfigured zeros, derived/mixed energy and live/cached SoC. Derived base load and aggregate device energy SHALL reflect all contributing source paths. Metadata SHALL describe the actual path, not just the application version or successful completion of a history request. Backfills SHALL retain their non-authoritative source while recording their measurement method, including accepted components in a partially recorder-owned row.

#### Scenario: One missing history entity
- **WHEN** only battery history is missing from a successful batch response
- **THEN** battery energy is labelled as snapshot-derived and other valid integrated fields retain their own history provenance
- **AND** the slot is not falsely labelled wholly integrated

#### Scenario: Zero snapshot contributes to an aggregate
- **WHEN** an enabled EV charger uses a zero-valued snapshot fallback while another charger has integrated energy
- **THEN** aggregate EV and derived base-load provenance reflect the mixed source

#### Scenario: Disabled versus unset
- **WHEN** a subsystem is disabled or an enabled required input is unconfigured
- **THEN** its zero provenance distinguishes those cases rather than treating them as equivalent measurements

#### Scenario: Cached battery charge level
- **WHEN** the recorder uses its last-known SoC fallback
- **THEN** the SoC source is cached and is not labelled live

### Requirement: Measurement metadata follows accepted corrections
Observation UPSERTs SHALL update values and corresponding provenance together. Retained authoritative values SHALL retain their method/ownership metadata; partial writes SHALL NOT certify untouched fields. Corrections without supported provenance SHALL mark overwritten fields unknown. Non-authoritative writes SHALL NOT overwrite authoritative battery energy or SoC or relabel retained values. Ordinary recording writes SHALL preserve unrelated flags, especially explicit exclusions. Changed annotated measurements SHALL invalidate their legacy attestation.

#### Scenario: Partial authoritative correction
- **WHEN** a live write corrects PV but supplies no battery measurement
- **THEN** stored battery energy and its provenance remain unchanged and corrected PV receives its own new provenance

#### Scenario: Backfill collision
- **WHEN** a backfill supplies different battery energy and SoC for a slot already owned by the recorder
- **THEN** retained authoritative values and their provenance are unchanged

#### Scenario: Backfill fills an unmeasured component
- **WHEN** a recorder-owned slot has no authoritative battery measurement and backfill fills it
- **THEN** that accepted battery value is identified as backfill-owned even though the row's overall source remains recorder
- **AND** it is not falsely certified for calibration

#### Scenario: Existing exclusion survives
- **WHEN** a new live observation updates a slot marked `exclude: true`
- **THEN** the exclusion remains set and metadata still truthfully describes accepted measurements

#### Scenario: An attested value changes
- **WHEN** a writer changes an energy or SoC measurement covered by legacy attestation
- **THEN** the stale attestation is invalidated instead of certifying the replacement
