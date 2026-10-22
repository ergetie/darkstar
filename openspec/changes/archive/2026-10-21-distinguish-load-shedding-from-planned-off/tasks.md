# Tasks

## 1. Separate intervention provenance from physical off state

- [x] 1.1 Add independent overload-intervention provenance and `actively_shedding` output in `executor/load_balancer.py`, retaining `shed` and switching clocks for physical commands; verify planned-off, first-managed off/unknown startup and requested-on startup waiting for capacity all remain safely commanded off without active shedding in `tests/executor/test_load_balancer_coordinated_ramping.py`.
- [x] 1.2 Implement intervention lifecycle and aggregate-state derivation, clearing on explicit off demand, granted restore, removal and disable without resetting off timestamps; verify actual overload cuts, delayed recovery across all restore gates, planned-off cancellation followed by planned-on demand, minimum-on deferral, unknown-demand protection and mixed EV/battery/stale state precedence with targeted balancer regressions.
- [x] 1.3 Distinguish physical command transitions from intervention start/end in decision logs and diagnostic snapshots; verify planned stops/startup never log shedding, cancellation never claims a physical restore, and snapshots expose command and intervention sets with accurate reasons.

## 2. Carry truthful status through the executor

- [x] 2.1 Serialize `actively_shedding` on every load entry through the shared REST/live-metrics status and keep all physical heater/binary-EV/custom actuation consumers on `shed`; verify payload coverage in `tests/executor/test_load_balancer_status_payload.py` and dispatch regressions in `test_coordinated_ramping_engine.py`/`test_load_balancer_wiring.py` showing routine off commands still actuate off.
- [x] 2.2 Switch load-shedding notifications to active-intervention edges and clean notification caches for removed/disabled entries; verify no plan-off/startup notifications, one notification for a genuine cut across recovery ticks, and a new notification for a later genuine episode. Exercise engine-resolved scheduled custom entities and explicit unknown-demand input separately.

## 3. Correct both cards and intervention attention

- [x] 3.1 Update the shared frontend status contract and compact/detail filters to consume `actively_shedding` (missing means inactive), migrating fixtures without changing layout; verify both card test suites exclude `shed: true, actively_shedding: false` and still display actual shedding.
- [x] 3.2 Add PowerFlow intervention-attention regressions proving ordinary off/startup payloads do not auto-switch tabs or show warning dots, genuine shedding does, and cancellation clears attention while an unrelated remaining intervention stays visible; run the relevant frontend Vitest suites.

## 4. Integration validation

- [x] 4.1 Run the affected backend suites with `UV_NO_SYNC=1 uv run python -m pytest` and the affected frontend suites using the repository's existing pnpm test command; verify actual overload reduction, safe restore ordering and minimum-on/off protections remain covered alongside truthful UI/notification behavior.
- [x] 4.2 Run `./scripts/lint.sh` and `openspec validate distinguish-load-shedding-from-planned-off --strict`; verify checks pass or document unrelated pre-existing failures without changing unrelated work.

## Workflow follow-up

- Use the requested apply/verify/archive workflow when implementation is authorized; leave implementation tasks unchecked during proposal creation.
- Obtain explicit approval before staging or committing, and separate approval before pushing. No manual deployment.
