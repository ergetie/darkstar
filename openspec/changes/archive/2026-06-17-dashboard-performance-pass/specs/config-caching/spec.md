## ADDED Requirements

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
