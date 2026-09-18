# DST-safe Time Operations

## Purpose

Provide DST-safe utilities for generating timezone-aware date ranges and localizing timestamps without crashing on DST transitions.

## Requirements

### Requirement: DST-safe date range generation
The system SHALL provide a `dst_safe_date_range(start, end, freq, tz, **kwargs)` function in `utils/time_utils.py` that generates timezone-aware DatetimeIndex values without crashing on DST transitions. The function SHALL convert start/end to UTC, generate the range in UTC, then convert to the target timezone.

#### Scenario: Spring-forward date range
- **WHEN** `dst_safe_date_range` is called with `start=2026-03-29 00:00` and `end=2026-03-29 06:00` in `Europe/Stockholm` with `freq="15min"`
- **THEN** the result MUST NOT contain any timestamps between 02:00 and 03:00 local time, MUST NOT raise an error, and MUST contain the correct number of slots for a 5-hour span (20 slots)

#### Scenario: Fall-back date range
- **WHEN** `dst_safe_date_range` is called with `start=2026-10-25 00:00` and `end=2026-10-25 06:00` in `Europe/Stockholm` with `freq="15min"`
- **THEN** the result MUST contain slots for both occurrences of the 02:00–02:45 hour (with different UTC offsets), MUST NOT raise an error, and MUST contain the correct number of slots for a 7-hour span (28 slots)

#### Scenario: Non-DST date range
- **WHEN** `dst_safe_date_range` is called on a date with no DST transition
- **THEN** the result MUST be identical to a standard `pd.date_range` call with the same parameters

### Requirement: DST-safe timestamp localization
The system SHALL provide a `dst_safe_localize(timestamps, tz)` function in `utils/time_utils.py` that localizes naive timestamps or Series without crashing on DST transitions. For nonexistent times, it SHALL shift forward to the next valid time. For ambiguous times, it SHALL infer the correct offset.

#### Scenario: Localize series containing spring-forward timestamp
- **WHEN** `dst_safe_localize` is called with a pandas Series containing `2026-03-29 02:30:00` in `Europe/Stockholm`
- **THEN** the timestamp MUST be shifted forward to `2026-03-29 03:00:00 CEST` and MUST NOT raise an error

#### Scenario: Localize series containing fall-back timestamp
- **WHEN** `dst_safe_localize` is called with a pandas Series containing `2026-10-25 02:30:00` in `Europe/Stockholm`
- **THEN** the timestamp MUST be localized without error, inferring the correct DST offset

### Requirement: All production date ranges use DST-safe functions
All `pd.date_range()` calls in production code that use a non-UTC `tz` parameter MUST be replaced with `dst_safe_date_range`. All `.tz_localize()` calls on non-UTC local timezones in production code MUST be replaced with `dst_safe_localize`.

#### Scenario: Planner runs during spring-forward transition
- **WHEN** the planner runs at any time on a spring-forward DST transition day
- **THEN** the planner MUST complete successfully and produce a valid schedule with no gaps except the nonexistent hour

#### Scenario: Planner runs during fall-back transition
- **WHEN** the planner runs at any time on a fall-back DST transition day
- **THEN** the planner MUST complete successfully and produce a valid schedule covering both occurrences of the ambiguous hour

### Requirement: Regression guard against bare DST-unsafe calls
The system SHALL include a test that scans production Python files for bare `pd.date_range` calls with non-UTC `tz` parameters and bare `.tz_localize()` calls with non-UTC targets. The test MUST fail if any such calls are found outside of `utils/time_utils.py`.

The guard SHALL additionally scan the planner and scheduler retry path for naive `datetime.now()` and `datetime.utcnow()` calls whose results are stored on, or compared against, cross-module scheduling state. Such calls MUST fail the guard, because a naive local timestamp handed to a UTC-based consumer silently shifts by the host's UTC offset instead of raising.

The guard SHALL cover at minimum `backend/services/planner_service.py` and `backend/services/scheduler_service.py`. Naive `datetime.now()` used purely to measure an elapsed duration within a single function SHALL NOT be flagged, provided the line carries the exact elapsed-duration exemption comment.

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
- **WHEN** a function captures `start = datetime.now()` and later computes `datetime.now() - start` without storing either value outside the function, with the exact exemption comment
- **THEN** the regression guard test MUST pass
