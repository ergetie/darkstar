## Why

The executor can select grid charging when a battery-charging plan expects zero grid import: it reads total battery charging and infers the source from zero export. A recorded solar-only slot reproduces this command mismatch, but neither its financial impact nor the physical effect of the proposed correction has been established.

## What Changes

- Preserve planned grid-charging intent separately from total battery charging when parsing schedules.
- Select solar/self-consumption mode for explicit zero grid charging, including when grid export is zero.
- Preserve that intent through EV battery source isolation.
- Retain existing behavior for legacy schedules that contain no charging-source information, and preserve explicit runtime overrides.
- Specify regression coverage and separate software verification from inverter validation and financial attribution.

These artifacts document a local, uncommitted patch created before the OpenSpec workflow. The user has now requested software correctness verification. Financial savings are not an acceptance criterion: another agent's analysis reported no financial benefit. Existing Fronius `Auto` behavior is accepted for this change and is not being redesigned or physically revalidated.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `executor`: Preserve charging-source intent from schedules through normal mode selection and EV source isolation, with explicit legacy compatibility.

## Impact

- Candidate implementation: `executor/override.py`, `executor/engine.py`, and `executor/controller.py`.
- Regression tests: `tests/executor/test_executor_controller.py` and `tests/executor/test_executor_engine.py`.
- Profile behavior affected by selection: Fronius maps charge to `Charge from Grid` and self-consumption to `Auto`; Deye enables grid charging only in charge mode.
- No database migration, new dependency, public API change, solver objective change, or production configuration change is proposed.
- Financial-baseline corrections, manual EV demand forecasting, and the replay being handled by another agent remain separate work.
