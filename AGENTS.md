# AGENTS.md - Development Guidelines for Darkstar Energy Manager

## Build & Test Commands

### Python Environment
- **Python version**: 3.12.0 (see .python-version)
- **Virtual environment**: Located in `venv/` directory
- **Install dependencies**: `pip install -r requirements.txt` (if available) or install packages individually
- **Run main planner**: `python planner.py`
- **Test inputs module**: `python inputs.py`
- **Run full test suite**: `PYTHONPATH=. python -m pytest -q`
- **Run single test**: `python -m pytest tests/test_module.py::test_function -v` (if pytest is used)

### Key Dependencies
- `pandas` - Data manipulation and analysis
- `pyyaml` - YAML configuration file parsing
- `nordpool` - Electricity price data fetching
- `pytz` - Timezone handling
- `requests` - REST clients for Home Assistant and forecasts
- `flask` - Web UI and diagnostics API layer
- `lightgbm`: Aurora ML models


## Code Style Guidelines

### Imports
- Group imports: standard library, third-party, local modules
- Use explicit imports: `import yaml` not `from yaml import *`
- Order alphabetically within groups
- Example:
```python
import json
from datetime import datetime, timedelta

import pandas as pd
import pytz
import yaml

from inputs import get_all_input_data
```

### Formatting & Types
- Use 4 spaces for indentation (no tabs)
- Maximum line length: 88 characters (Black default)
- Use type hints for function signatures and return types
- Follow PEP 8 naming conventions:
  - `snake_case` for variables and functions
  - `PascalCase` for classes
  - `UPPER_CASE` for constants

### Error Handling
- Use specific exceptions: `except ValueError:` not `except:`
- Handle external API calls with try/except blocks
- Log errors with context information
- Fail gracefully with meaningful error messages

### Configuration
- All user-configurable parameters in `config.yaml`
- Use nested structure with logical groupings (battery, thresholds, etc.)
- Provide default values in code for missing config keys
- Validate configuration values on startup
- `charging_strategy.price_smoothing_sek_kwh` controls price tolerance (smoothing block now covers only hysteresis settings)
- `charging_strategy.block_consolidation_tolerance_sek` allows merging adjacent charge slots when price spread is within tolerance (fallback to smoothing when unset)
- `charging_strategy.consolidation_max_gap_slots` caps how many zero-capacity slots can exist inside a consolidated block
- `learning.sqlite_path` stores planner telemetry (ensure parent directory exists before running)
- `s_index` supports `mode` (`static` or `dynamic`), `base_factor`, `max_factor`, `pv_deficit_weight`, `temp_weight`, `temp_baseline_c`, `temp_cold_c`, and `days_ahead_for_sindex`
- `secrets.yaml` must include Home Assistant sensor IDs: `battery_soc_entity_id` and `water_heater_daily_entity_id`
- `arbitrage` adds peak export controls: `export_percentile_threshold`, `enable_peak_only_export`, `export_future_price_guard`, `future_price_guard_buffer_sek`

### Data Processing
- Use pandas DataFrames for time-series data
- Apply timezone-aware datetime handling
- Process data in logical passes (see planner.py structure)
- Maintain data immutability where possible

### Testing & Validation
- Test edge cases (empty data, missing config, API failures)
- Validate output JSON schema matches expected format
- Test with realistic data ranges
- Verify timezone handling across daylight saving transitions

### Documentation
- Use docstrings for all public functions and classes
- Include parameter types and return value descriptions
- Add inline comments for complex business logic
- Maintain README with setup and usage instructions

### Process Policy
- Before implementing any newly drafted revision/plan section (e.g., after we agree on a fix plan), switch to the designated implementation model. Planning and discussion should happen first; code changes should only be made after switching models.
- **Planning**: Before implementing, ensure the revision is active in `PLAN.md`.
- **History / Archival**:
  - A revision may be moved from `PLAN.md` to `CHANGELOG.md` **only** when:
    - The relevant project phase (e.g. an Antares phase) is fully completed and validated, and
    - The Product Owner has explicitly confirmed that the revision is ready to be archived.
  - Once moved, the revision should live in **one place only** (the changelog), not duplicated in `PLAN.md` (a short pointer is fine if needed).
  - While an Antares phase is active, keep its revisions in `PLAN.md` for context; do not archive them without prior confirmation.

### Git & Data Hygiene
- Treat `config.yaml` as environment-specific. Do **not** commit server-only edits; keep long-lived defaults in `config.default.yaml` and copy/merge locally.
- Never commit runtime data:
  - `data/planner_learning.db` (SQLite telemetry)
  - `data/scheduler_status.json`
  - `schedule.json`
- When deploying to a server, prefer `git stash` / `git restore` to keep local DB and schedules, then `git checkout` the desired branch.

### Tooling
- After major code changes or a completed revision:
  - Run `black .` (or the project’s configured formatter) to normalize formatting.
  - Run `flake8 .` to catch style and lint issues before committing.

## Project Structure
- `backend/` - Flask API, Strategy Engine (`backend/strategy/`), and internal Scheduler (`backend/scheduler.py`).
- `frontend/` - React + Vite UI application.
- `ml/` - Aurora Machine Learning pipeline (`train.py`, `forward.py`).
- `inputs.py` - Data fetching (Home Assistant, Nordpool).
- `planner.py` - Core MPC scheduling logic.
- `config.yaml` - Master configuration.
- `backend/themes/` - UI theme files (JSON/YAML).

### Key Business Logic
- Multi-pass Model Predictive Control (MPC) approach
- Strategic charging during low-price periods
- Cascading responsibility between time windows
- Integrated water heating scheduling
- "Hold in cheap windows" principle to preserve battery

### Output Requirements
- Generate `schedule.json` with proper schema
- Include slot numbers, timestamps, classifications
- Round numerical values to 2 decimal places
- Ensure timezone-aware ISO format timestamps
