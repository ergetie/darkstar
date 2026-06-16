## ADDED Requirements

### Requirement: Single Live Recorder Instance

Exactly one live recorder instance SHALL write `slot_observations` energy and price columns at runtime. The deployment runtime SHALL NOT start more than one concurrent recorder, and the in-process `RecorderService` (started by `backend/main.py`) SHALL be the single canonical live recorder. Container entrypoints SHALL NOT additionally launch the standalone `python -m backend.recorder` loop alongside the application server.

This requirement closes the interaction with the Correctable Energy Storage requirement: because authoritative writes use last-writer-wins (so genuine zeros and downward corrections can be stored), two concurrent recorders sharing the meter-state file (`data/recorder_state.json`) will race — the later writer reads the already-advanced cumulative state, computes a zero delta, and overwrites the earlier writer's real measurement with `0.0`. A single live recorder makes the shared-state delta calculation and the authoritative overwrite well-defined.

#### Scenario: Application server starts exactly one recorder

- **WHEN** the container starts the application server (`uvicorn backend.main:app`)
- **THEN** the in-process `RecorderService` SHALL be the only recorder loop running
- **AND** no standalone `python -m backend.recorder` process SHALL be launched alongside it

#### Scenario: Entrypoint does not launch a standalone recorder

- **WHEN** `scripts/docker-entrypoint.sh` runs
- **THEN** it SHALL NOT invoke `python -m backend.recorder` (neither at initial startup nor in any process-monitor/restart block)
- **AND** it SHALL rely on the application server's in-process recorder for live observation recording

#### Scenario: A second concurrent recorder cannot silently zero out real data

- **WHEN** a real cumulative-meter delta has been recorded for a slot by the single live recorder
- **AND** any additional recorder loop were to run against the same shared meter-state file
- **THEN** the system design SHALL prevent that second loop from overwriting the real measurement with a zero delta — enforced by ensuring only one recorder instance runs

#### Scenario: Add-on and root entrypoints are consistent

- **WHEN** the system is deployed via either the root `Dockerfile` (`scripts/docker-entrypoint.sh`) or the HA add-on Dockerfiles (`darkstar/run.sh`, `darkstar-dev/run.sh`)
- **THEN** both topologies SHALL run exactly one live recorder (the in-process `RecorderService`)
