## MODIFIED Requirements

### Requirement: Regression guard against bare DST-unsafe calls
The system SHALL include a test that scans production Python files for bare `pd.date_range` calls with non-UTC `tz` parameters and bare `.tz_localize()` calls with non-UTC targets. The test MUST fail if any such calls are found outside of `utils/time_utils.py`.

The guard SHALL additionally scan the planner and scheduler retry path for naive `datetime.now()` and `datetime.utcnow()` calls whose results are stored on, or compared against, cross-module scheduling state. Such calls MUST fail the guard, because a naive local timestamp handed to a UTC-based consumer silently shifts by the host's UTC offset instead of raising.

The guard SHALL cover at minimum `backend/services/planner_service.py` and `backend/services/scheduler_service.py`. Naive `datetime.now()` used purely to measure an elapsed duration within a single function SHALL NOT be flagged, since both ends of such a subtraction share the same representation.

#### Scenario: New code introduces bare pd.date_range with local tz
- **WHEN** a developer adds `pd.date_range(..., tz=some_local_tz)` to a production file
- **THEN** the regression guard test MUST fail in CI

#### Scenario: Safe calls are not flagged
- **WHEN** production code uses `dst_safe_date_range` or `pd.date_range(..., tz="UTC")`
- **THEN** the regression guard test MUST pass

#### Scenario: New code introduces naive datetime.now in the retry path
- **WHEN** a developer assigns `datetime.now()` to a retry or scheduling timestamp in `planner_service.py` or `scheduler_service.py`
- **THEN** the regression guard test MUST fail in CI

#### Scenario: Aware UTC scheduling timestamps are not flagged
- **WHEN** scheduling code uses `datetime.now(UTC)`
- **THEN** the regression guard test MUST pass

#### Scenario: Local elapsed-time measurement is not flagged
- **WHEN** a function captures `start = datetime.now()` and later computes `datetime.now() - start` without storing either value outside the function
- **THEN** the regression guard test MUST pass
