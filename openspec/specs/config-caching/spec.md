# Config Caching

## Purpose

Configuration caching with file modification time detection to reduce unnecessary disk I/O.

## Requirements

### Requirement: Config YAML is cached with file-mtime detection
The executor SHALL cache the parsed config and inverter profile in memory. Before each tick, the executor SHALL check the file modification timestamp of `config.yaml` and the active profile YAML. The config SHALL only be re-parsed from disk when the mtime has changed since the last read.

#### Scenario: Config file unchanged between ticks
- **WHEN** the executor starts a new tick
- **AND** `config.yaml` has not been modified since the last tick
- **THEN** the executor uses the cached config without reading from disk
- **AND** no YAML parsing occurs

#### Scenario: Config file modified between ticks
- **WHEN** the executor starts a new tick
- **AND** `config.yaml` has been modified since the last tick (mtime changed)
- **THEN** the executor re-reads and re-parses the config from disk
- **AND** the cached config is updated with the new values

#### Scenario: Profile YAML cached independently
- **WHEN** the executor starts a new tick
- **AND** the inverter profile YAML file has not been modified since the last read
- **THEN** the cached profile is reused without disk I/O or YAML parsing

#### Scenario: Profile switches when config changes profile name
- **WHEN** the user changes `inverter_profile` in config.yaml from `fronius` to `deye`
- **AND** the executor detects the config mtime change
- **THEN** the executor re-parses the config, detects the profile name change
- **AND** loads and caches the new profile YAML

#### Scenario: First tick after startup
- **WHEN** the executor starts for the first time
- **THEN** the config and profile are read from disk and cached
- **AND** subsequent ticks use the cache until a file changes

### Requirement: Shared config loader caches parsed YAML with mtime detection
The shared configuration loader (`backend/core/secrets.py:load_yaml`) used by the web/API request path SHALL cache parsed YAML in memory keyed by file path. On each call it SHALL compare the file's current modification time against the cached entry and re-parse from disk only when the mtime has changed. This applies to all configuration files read through the loader, including `config.yaml` and `secrets.yaml`.

#### Scenario: File unchanged since last read
- **WHEN** `load_yaml("config.yaml")` is called
- **AND** `config.yaml` has not been modified since the last cached read
- **THEN** the loader returns the cached parse
- **AND** no file read or YAML parsing occurs

#### Scenario: File modified since last read
- **WHEN** `load_yaml("config.yaml")` is called
- **AND** `config.yaml`'s mtime has changed since the last cached read (e.g. a config migration or reflex update wrote it)
- **THEN** the loader re-reads and re-parses the file from disk
- **AND** updates the cached entry with the new mtime and parsed content

#### Scenario: secrets.yaml cached independently
- **WHEN** `secrets.yaml` is read repeatedly through the loader during a request (e.g. once per Home Assistant entity)
- **AND** `secrets.yaml` has not changed
- **THEN** subsequent reads return the cached parse without disk I/O or parsing

#### Scenario: First read after startup
- **WHEN** a file is read through the loader for the first time
- **THEN** it is read from disk, parsed, and cached
- **AND** subsequent reads use the cache until the file's mtime changes

### Requirement: Cached config is returned as an independent copy
The shared loader SHALL return a copy of the cached parse to each caller, so that a caller mutating the returned structure cannot corrupt the shared cache for other callers.

#### Scenario: Caller mutates returned config
- **WHEN** a caller receives a config dict from the loader and modifies it in place
- **THEN** the in-memory cache is unaffected
- **AND** a subsequent call returns the original cached values

### Requirement: Concurrent reads of the cached config are safe
The shared loader SHALL serialize cache reads and parse-on-miss with a lock, so that concurrent access from the event loop, `asyncio.to_thread` workers, and the executor thread cannot corrupt the cache or trigger duplicate parses for the same unchanged file.

#### Scenario: Concurrent requests read config simultaneously
- **WHEN** multiple requests call the loader for the same unchanged file at the same time
- **THEN** each receives a valid parsed copy
- **AND** the cache remains consistent

### Requirement: Forecast layer uses current config, not a startup snapshot

The forecast layer SHALL run on the current on-disk configuration. The shared `LearningEngine` (obtained via `get_learning_engine()`) caches its parsed config; before each forecast generation it SHALL detect a change in `config.yaml`'s modification time and re-parse from disk when the mtime has changed, so that load, PV, and price forecasts — and all config-derived inputs (solar-array geometry, inverter limits, weather location, PV tuning) — reflect the latest saved values without requiring a process restart. Re-parsing SHALL be mtime-gated so an unchanged config incurs no repeated disk I/O.

#### Scenario: Config unchanged between forecast runs
- **WHEN** a forecast run starts
- **AND** `config.yaml` has not been modified since the engine last read it
- **THEN** the engine reuses its cached config without re-reading from disk

#### Scenario: Config edited after process startup
- **WHEN** the user changes an inverter limit (e.g. `system.inverter.max_ac_power_kw`) in `config.yaml` while the backend is running
- **AND** a forecast run starts after the change
- **THEN** the engine detects the changed mtime, re-parses the config
- **AND** the resulting forecast uses the new inverter limit, not the value present at startup

#### Scenario: Forecast layer and planner agree on config
- **WHEN** config is changed while the backend is running
- **AND** both a planner run and a forecast run occur afterwards
- **THEN** the forecast layer SHALL use the same current config values the planner uses
- **AND** no split-brain (planner-on-new, forecast-on-old) state occurs

### Requirement: Config save refreshes the forecast layer

Saving configuration through the API SHALL propagate the change to the forecast layer, not only the executor. After a successful config write, the `LearningEngine`'s cached config SHALL be invalidated or refreshed so the next forecast uses the saved values.

#### Scenario: Config saved through the UI/API
- **WHEN** a config save completes successfully via the config API
- **THEN** the executor reload is triggered as before
- **AND** the `LearningEngine` cached config is invalidated or refreshed
- **AND** the next forecast run reads the newly saved values
