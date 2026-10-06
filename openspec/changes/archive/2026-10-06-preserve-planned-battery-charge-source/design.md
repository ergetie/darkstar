## Context

The Kepler adapter already emits two different schedule values:

- `battery_charge_kw`: total planned battery charging.
- `charge_kw`: `min(battery charge energy, grid import energy) / slot duration`, used as planned grid-charging intent.

`ExecutorEngine._parse_slot_plan` previously kept only the first value. `Controller._follow_plan` selected charge mode whenever battery charging was positive and export was zero. A solar surplus fully absorbed by the battery satisfies that condition despite zero planned grid import.

The cmon89 snapshot contains a concrete example on October 4, 2026, at 10:00 local time: stored planned battery charge 0.18958 kWh, grid import 0, export 0, and recorded EV energy 0. At 10:10, the execution log reports `Charge from Grid` already active and a verified grid-charge setting of 800 W. Running the previous and candidate controllers with the recorded plan yields `charge` and `self_consumption`, respectively. This verifies the source-selection discrepancy, not unnecessary imports or their cost. Slot plans are the latest stored values, not a complete history of every planner run.

The current patch is local and uncommitted and predates this OpenSpec. The user subsequently requested correctness tests, excluded proof of financial savings, and accepted the existing `Auto` mode behavior. Production was accessed read-only and was not changed.

## Goals / Non-Goals

**Goals:**

- Preserve the charging-source information already available in schedules.
- Honor explicit zero grid charging during normal planned operation.
- Preserve this distinction through EV source isolation.
- Verify the charging-source contract through planner formatting, parsing, mode selection, and real profile action definitions with mocked Home Assistant I/O.

**Non-Goals:**

- Change MILP optimization, EV forecasting, water-heater scheduling, or battery-hold decisions.
- Correct the financial baseline or duplicate the other agent's replay.
- Infer exact physical charging-source shares or quantify savings from command logs.
- Deploy, release, archive, commit, or change production settings as part of artifact creation.

## Decisions

### Carry source intent separately from total battery power

The candidate adds optional `SlotPlan.grid_charge_kw`. Zero is an explicit solar-only instruction; `None` means the schedule lacks source information. Total `charge_kw` inside `SlotPlan` retains its existing meaning as battery charging power. Reusing the existing total-power field would lose the distinction again.

### Prefer explicit intent and preserve zero

Schedule parsing uses non-null schedule `charge_kw` first, including zero. When absent, it derives intent from `grid_import_kw`, capped by total battery charging; otherwise from `import_kwh` converted using the executor's existing 15-minute slot convention. If none exists, intent remains unknown.

Deriving from current measured PV was considered but would replace planner intent with a new runtime control policy. Adding a new planner output field was also considered; the existing adapter fields already resolve the observed zero-import case. The existing mixed-source proxy is used for mode selection only; this change does not redefine the charge-power command.

### Select modes from source intent

During normal operation, positive total charging with explicit zero grid charging uses `self_consumption`. Positive grid-charging intent with positive total charging uses `charge`. Planned battery export retains priority. Explicit runtime overrides remain separate and can intentionally request charging regardless of the schedule.

When intent is unknown, retain the previous rule for legacy schedules. This limits compatibility changes but intentionally leaves their ambiguous source classification unresolved.

### Preserve intent during EV source isolation

The engine rebuilds a slot when blocking battery discharge into an EV. It must copy `grid_charge_kw`, so that an explicit zero cannot become unknown and fall back to the old inference.

### Keep software and physical acceptance separate

Acceptance is software correctness: planner-to-formatter-to-executor integration and Fronius/Deye profile dispatch with mocked Home Assistant I/O. These checks do not establish physical inverter behavior or economic benefit. Per the user's scope correction, proof of savings and physical revalidation of the existing `Auto` behavior are not release gates for this change.

## Risks / Trade-offs

- **Legacy source ambiguity** → Preserve prior behavior only when all supported source fields are absent or null; document and test the boundary.
- **Mixed-source allocation is a proxy** → The adapter's `min(charge, import)` does not independently identify physical energy provenance. Review its semantics before extending claims beyond the observed zero-import case.
- **Fronius automatic operation differs from forced charging** → Existing `Auto` behavior is accepted by the user and remains unchanged; tests verify selection and dispatch, not the inverter's physical response to PV changes.
- **Grid-charge power uses total battery charge** → For a 3 kW total / 1 kW grid plan, Fronius still receives 3,000 W. The [integration source](https://github.com/redpomodoro/fronius_modbus/blob/main/custom_components/fronius_modbus/froniusmodbusclient.py) implements this entity by writing a negative battery discharge-rate register (`set_grid_charge_power` → `set_discharge_rate_w`), not a grid-meter target. This supports, but does not physically prove, interpreting the value as a battery-charge target. It is not a confirmed power-allocation bug and is not a release gate for this source-selection change. Power commands remain unchanged.
- **Forecast errors and meter inconsistencies** → A grid-charge command plus recorded imports is not a causal loss measurement. Use the separate replay and device measurements for attribution.
- **Test warning** → The earlier suite emitted an unawaited `AsyncMock` coroutine warning because the skipped-action test supplied an unconfigured asynchronous mock as system state. The test now returns a real `SystemState`; subsequent verification checks for recurrence.

## Migration Plan

No database migration or schedule-format migration is required. Complete software/profile verification and OpenSpec review before archive/release consideration. Deployment is a separate action. For any future deployment, rollback means reverting the reviewed executor code and restoring the previous application version; no runtime data should be rewritten.

## Open Questions

- Is legacy fallback acceptable, or should source-less schedules be rejected through a separate compatibility change?
- The integration's battery-rate implementation supports retaining total battery charge power. Exact installed firmware behavior is not being inferred or modified by this change.
- Financial comparison and physical `Auto` behavior are outside this change's acceptance scope.
