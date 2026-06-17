## ADDED Requirements

### Requirement: Diagnose-only boundary
The stabilization review SHALL NOT modify any application code, configuration, schema, or dependency. It SHALL only produce documentation artifacts. Candidate remedies for any finding SHALL be recorded as text, never implemented within this change.

#### Scenario: No application files are edited
- **WHEN** any phase of the review runs
- **THEN** no file under `backend/`, `planner/`, `ml/`, `executor/`, nor any runtime/config/schema file is created, edited, or deleted
- **AND** the only files written are within `openspec/changes/stabilization-review/`

#### Scenario: Remedies are recorded, not applied
- **WHEN** a reviewer identifies a possible fix (e.g. a PV sanity clamp or a hybrid-disable toggle)
- **THEN** the remedy is written into the finding's "Candidate remedies" field
- **AND** no code implementing the remedy is written in this change

### Requirement: Findings ledger is the single source of truth
The review SHALL maintain a single `findings.md` ledger as an append-only numbered list. Each finding SHALL be self-contained so a fresh session can act on it without conversation history. Findings SHALL NOT be renumbered or deleted; a retracted finding SHALL have its status set to `wontfix`.

#### Scenario: A new finding is added
- **WHEN** a reviewer confirms a bug, smell, or risk
- **THEN** it is appended as the next numbered finding
- **AND** it includes severity, domain, status, location (`file:line`), symptom, root-cause hypothesis, candidate remedies, and the phase it was found in

#### Scenario: A finding is retracted
- **WHEN** a previously recorded finding is determined to be invalid
- **THEN** its number and entry are retained
- **AND** its status is changed to `wontfix` with a reason, rather than being deleted

#### Scenario: Pre-seeded known issues
- **WHEN** the ledger is first created
- **THEN** it contains the EV-from-PV economics bug (S1), the PV hybrid 2× overestimate (S2), and the CI-only-runs-API-tests gap (S4) as findings #1–#3

### Requirement: Severity classification
Every finding SHALL be assigned exactly one severity from S1–S4: S1 (wrong physical action / safety / money loss), S2 (wrong decision input), S3 (bounded correctness bug), S4 (smell / debt / missing test).

#### Scenario: Finding is classified
- **WHEN** a finding is recorded
- **THEN** it carries exactly one of S1, S2, S3, or S4
- **AND** the severity reflects the rubric defined in `design.md`

### Requirement: Phased, resumable execution
The review SHALL be organized into phases (0 baseline, 1 anchor spikes, 2a broad pass, 2b deep dives, 3 architecture) tracked at per-phase/per-domain granularity in `tasks.md`. Each phase SHALL be runnable in an independent session.

#### Scenario: A phase session resumes work
- **WHEN** a new session begins a phase
- **THEN** it reads `design.md` and `findings.md` first
- **AND** it performs only the phase named in its `tasks.md` block
- **AND** on completion it appends findings and ticks that phase's checkbox

#### Scenario: Anchor spikes stay diagnostic
- **WHEN** Phase 1 investigates the PV or EV anchor bug
- **THEN** it produces a documented root cause
- **AND** it does not design or implement a fix

### Requirement: Behavior-traced investigation
Investigation SHALL trace concrete scenarios through the code, not rely on file skims alone. Each finding's root-cause hypothesis SHALL be marked CONFIRMED (verified by tracing) or UNVERIFIED. Subagents used for fan-out SHALL be read-only and SHALL NOT triage.

#### Scenario: A subagent reports a finding
- **WHEN** a fan-out subagent surfaces a candidate issue
- **THEN** it returns `file:line`, symptom, and mechanism with a CONFIRMED/UNVERIFIED flag
- **AND** the issue is marked `confirmed` only after operator triage
