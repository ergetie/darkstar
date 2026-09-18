## ADDED Requirements

### Requirement: Dead learning tables and models are removed

The system SHALL NOT define or retain the following tables or their ORM models, none of which has a reader anywhere in the codebase: `battery_cost`, `antares_rl_runs`, `antares_training_runs`, `antares_policy_runs`, `training_episodes`, `strategy_log`, `daily_water`, `sensor_totals`, `realized_energy`.

The `battery_cost` table was written every executor tick by a tracker whose read methods had no callers. The three `antares_*` tables belong to an abandoned reinforcement-learning experiment whose code no longer exists. `training_episodes` was written only behind a `debug.enable_training_episodes` flag that exists at no configuration or UI surface, making the write path unreachable. The remainder are defined in the ORM and referenced nowhere else.

#### Scenario: Models no longer defined
- **WHEN** the codebase is searched for `BatteryCost`, `AntaresRLRun`, `AntaresTrainingRun`, `AntaresPolicyRun`, `TrainingEpisode`, `StrategyLog`, `DailyWater`, `SensorTotal`, or `RealizedEnergy`
- **THEN** no ORM model, index, reader, or writer references them (test fixtures aside)

#### Scenario: Battery cost tracking module is gone
- **WHEN** the codebase is searched for `BatteryCostTracker` or `_update_battery_cost`
- **THEN** no module, call site, or import references them
- **AND** the executor tick performs no battery cost write and no Nordpool fetch on their behalf

#### Scenario: Training-episode code paths are gone
- **WHEN** the codebase is searched for `store_training_episode`, `get_episodes_count`, or `enable_training_episodes`
- **THEN** no reference remains
- **AND** `bin/inspect_episodes.py` is deleted
- **AND** `scripts/health_check.py` no longer reports a "Training Episodes" row

#### Scenario: Migration drops the tables
- **WHEN** `alembic upgrade head` runs against a database containing any of these tables
- **THEN** each table present is dropped
- **AND** a table already absent SHALL NOT cause the upgrade to fail
- **AND** `alembic downgrade -1` recreates all nine (empty) tables for rollback parity

### Requirement: No dead field is served by the learning status API

`GET /api/learning/status` SHALL NOT return a `training_episodes` field, which could only ever report zero once the write path is removed.

#### Scenario: Status response omits the dead field
- **WHEN** a client requests `GET /api/learning/status`
- **THEN** the response SHALL NOT contain a `training_episodes` key
- **AND** the remaining status fields SHALL be unchanged
