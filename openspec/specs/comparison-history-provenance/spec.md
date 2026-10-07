# Comparison History Provenance

## Purpose

Defines evidence-based review and maintenance of historical energy measurement provenance.

## Requirements

### Requirement: Historical provenance requires explicit installation evidence
The system SHALL provide a local history annotation tool using an explicit database path and versioned manifest containing database/affected-measurement identity, timezone-aware half-open intervals, supported source/semantics and boundary declarations, dispositions and reviewable evidence references/digests. Inclusion SHALL require evidence of configured measurement paths, full-slot energy semantics, compatible boundaries and relevant fallback treatment. Unknown intervals SHALL remain unknown. The tool SHALL NOT derive inclusion from a passing fit, decimal precision, an app release date alone or a universal date. Legacy attestation SHALL remain distinct from actually observed modern per-component provenance.

#### Scenario: Deployment transition proves an exclusion
- **WHEN** installation evidence identifies an older snapshot-era interval
- **THEN** that interval can be marked excluded without changing its numerical observations

#### Scenario: Verified historical energy
- **WHEN** reviewed evidence establishes compatible full-slot measured-energy provenance for a legacy interval
- **THEN** the manifest can attest that interval with its evidence identity
- **AND** numeric eligibility, excitation and accuracy gates still apply

#### Scenario: Insufficient inclusion evidence
- **WHEN** a deployment date is known but measurement sources or fallback treatment cannot be established
- **THEN** unsupported history is not promoted to trustworthy measured energy

#### Scenario: Other installation
- **WHEN** another installation has different deployment dates, sensors or capacity
- **THEN** its own evidence and configured capacity are used without the first installation's constants

### Requirement: Annotation is inspectable local metadata maintenance
Dry run SHALL be the default and SHALL report affected counts, classifications, conflicts and cohort eligibility without writes. Apply SHALL require an explicit reviewed manifest and maintenance use against a local database, create a SQLite backup, verify unchanged preimages, and atomically update only comparison-owned quality metadata. It SHALL preserve all energy/price/SoC values, source ownership, exclusions and unrelated flags. It SHALL reject stale/wrong identities, ambiguous or overlapping intervals, promotion of known snapshots/backfills, and replacement of observed modern provenance. The tool SHALL have no automatic startup or remote write behavior.

#### Scenario: Dry run
- **WHEN** the operator omits the explicit apply option
- **THEN** the tool produces an inspectable report and the database is unchanged

#### Scenario: Metadata-only application
- **WHEN** a valid reviewed manifest is applied
- **THEN** only comparison-owned `quality_flags` keys change in one transaction after backup
- **AND** numerical observation fields and existing exclusions are unchanged

#### Scenario: Conflicting source evidence
- **WHEN** a manifest attempts to certify an observed snapshot or backfilled row as trusted measured recorder energy
- **THEN** the application is rejected

#### Scenario: Stale target
- **WHEN** affected measurements changed after the manifest was prepared
- **THEN** application aborts without partial metadata writes

### Requirement: Annotation is idempotent and safely reversible
The tool SHALL produce an audit/undo record containing manifest/evidence identities and comparison-metadata preimages/postimages, without credentials. Identical application SHALL be idempotent. Undo SHALL restore only comparison-owned metadata and SHALL refuse rows whose postimages or measurements changed after application. Restoring annotations SHALL invalidate comparison caches through the normal provenance identity mechanism.

#### Scenario: Apply twice
- **WHEN** the same valid manifest is applied to unchanged annotated rows again
- **THEN** metadata remains identical and no duplicate attestation is created

#### Scenario: Safe undo
- **WHEN** an unchanged annotation is undone
- **THEN** the previous comparison metadata is restored while unrelated flags and all numerical values remain unchanged

#### Scenario: New measurements after annotation
- **WHEN** a recorder correction changes an annotated measurement before undo
- **THEN** undo refuses that stale row rather than restoring certification of the old measurement
