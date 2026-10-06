# Verification Report: preserve-planned-battery-charge-source

Date: 2026-10-06. Scope: charging-source software correctness, as requested by the user. Proof of financial savings and physical revalidation of existing Fronius Auto behavior are explicitly excluded. Power-setting behavior is unchanged.

## Summary

| Dimension | Status |
| --- | --- |
| Completeness | 17/17 tasks complete |
| Correctness | 5/5 requirements covered by code and regression tests |
| Coherence | Implementation follows the source-preservation design and the user's corrected scope |
| Software validation | 810 executor tests passed, no warnings; changed-file lint/format and executor type checks passed |
| Device-profile coverage | Real Fronius/Deye YAML and production dispatcher exercised with mocked HA I/O |
| Assessment | Software verification passed; ready to archive and sync |

## Requirement and scenario mapping

| Requirement | Implementation | Regression evidence |
| --- | --- | --- |
| Separate total charge and grid intent | SlotPlan and ExecutorEngine._parse_slot_plan | TestParseSlotPlan.test_preserves_grid_charging_source: explicit zero, precedence, power/energy fallbacks, capping, null values and absent fields |
| Normal mode follows intent | Controller._follow_plan | Solar-only with/without export and positive grid charging; test_battery_export_precedes_explicit_charge_source; test_force_charge_override_precedes_solar_only_plan |
| EV isolation preserves intent | EV slot reconstruction in ExecutorEngine._tick | TestRunOnce.test_ev_isolation_preserves_charging_source: zero, positive, and unknown intent |
| Legacy compatibility | Unknown-intent fallback in Controller._follow_plan | Parser-to-controller source-less charge and source-less solar-export cases; existing executor regressions |
| Planner/profile boundaries | Adapter, formatter, parser, controller, real profiles and dispatcher | tests/executor/test_charge_source_pipeline.py: eight cases covering both profiles with solar-only, solar/export, grid-only and mixed charging |

The pipeline tests use real KeplerResult output types, kepler_result_to_dataframe, dataframe_to_json_response, a JSON serialization boundary, executor parsing, controller decisions, profile files loaded from disk, and ActionDispatcher.execute. Only Home Assistant I/O and timing are mocked. Tests assert actual select/switch writes, absence of forced Fronius grid-power writes for solar-only plans, and successful write verification.

## Validation results

- UV_CACHE_DIR=/tmp/darkstar-uv-cache UV_NO_SYNC=1 uv run python -m pytest tests/executor -q: **810 passed in 189.56 seconds**, no warnings.
- Ruff lint and format checks for the three implementation files and four changed/new test files: passed.
- UV_CACHE_DIR=/tmp/darkstar-uv-cache UV_NO_SYNC=1 uv run pyright executor/controller.py executor/engine.py executor/override.py: **0 errors, 0 warnings**.
- Strict OpenSpec change validation: passed.
- Previous-versus-corrected controller comparison with the recorded October 4 slot: previous charge, corrected self_consumption, with 0.75832 kW total battery charging and zero grid charging.

The previous suite's mock-coroutine warning was traced to an unconfigured AsyncMock returned as system state in test_executor_engine_ignores_skipped_actions. Supplying a real SystemState fixes the test setup; the full suite now completes without warnings. No production code was changed to suppress warnings.

## Charge-power interpretation

The existing Fronius command still uses total battery charging power. A local diagnostic with 3 kW total charging and 1 kW grid intent resolves the grid-charge entity command to 3,000 W. This fact alone does not establish over-import: the [integration source](https://github.com/redpomodoro/fronius_modbus/blob/main/custom_components/fronius_modbus/froniusmodbusclient.py) implements set_grid_charge_power through a negative battery discharge-rate register rather than a grid-meter setpoint. Total-power interpretation is therefore plausible; changing it to grid-only power without proving the installed integration/firmware semantics would be unjustified.

This is a documented interpretation question, not a confirmed additional bug or release blocker. Source selection is corrected; profile power allocation is unchanged.

## Findings

- **Critical:** none within the corrected software scope.
- **Warnings:** none blocking this correctness change. The retained legacy fallback and unchanged power-command semantics are explicitly documented design boundaries.
- **Skipped:** full application/frontend checks, live inverter validation, financial replay, deployment, commit, archive, and main-spec sync were not performed in this test-and-verification turn.

## Assessment

All specified software requirements and scenarios are covered. The change is ready for archive/sync and inclusion in the normal release workflow. This does not claim physical measurements or financial improvement. Production is unchanged and the patch is uncommitted.

## Lifecycle completion

On 2026-10-06, at the user's request, OpenSpec synced all five added executor requirements to `openspec/specs/executor/spec.md` and archived this change as `2026-10-06-preserve-planned-battery-charge-source`. All 17 tasks were complete. Staging, committing, and deployment were not performed.
