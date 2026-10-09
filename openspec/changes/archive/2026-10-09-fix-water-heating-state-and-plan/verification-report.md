# Verification: fix-water-heating-state-and-plan

Independent verification used the migrated `opsx:verify` workflow against the proposal, design, four delta specs and existing energy-recording, planner, per-device-water-scheduling and binary-control specifications. Checked production callers, persistence/correction behavior, forecast acquisition, pipeline filtering, adapter/solver constraints, API merging, chart datasets/rendered details and settings save behavior.

## Scorecard

| Dimension | Result |
| --- | --- |
| Completeness | 22/22 checked tasks; 11 delta requirements and 41 named scenarios mapped below |
| Correctness | Production-path and edge-case findings fixed; final checks passed |
| Coherence | Existing metadata storage, ownership rules, control contracts and design-system UI retained |
| Findings before fixes | 1 CRITICAL, 13 WARNING, 1 SUGGESTION |
| Findings after fixes | 0 CRITICAL, 0 WARNING, 0 SUGGESTION |

## Findings and fixes

1. **CRITICAL — wrong production progress cutoff.** The first whole-day price was midnight, while the pipeline selected a later first solver slot. Forecast acquisition now selects the actual upcoming solver slot, and the pipeline refreshes progress if acquisition crosses a slot boundary. The full store → forecasts → initial state → pipeline → adapter → real solver regression verifies both control modes and horizon advancement.
2. **WARNING — fractional boundaries and varying slot durations.** The solver previously assigned all slot energy by start time and multiplied by average duration. It now apportions constant planned power by each quota-window overlap and actual elapsed duration. A 06:07:30 regression satisfies both 0.125 kWh quotas with one 0.25 kWh slot.
3. **WARNING — repeated-hour storage ordering.** ISO text ordering could omit a second-occurrence 02:15 observation after a first-occurrence 02:30 quota boundary. The water accessor widens the indexed date query and filters timestamps as instants; an actual-store DST regression retains that contribution.
4. **WARNING — malformed device metadata.** Unhashable source/coverage values could crash a read. Parsing now checks source types and compares coverage safely; unavailable sources cannot certify complete coverage. Rejected inputs remain unknown.
5. **WARNING — unrelated provenance could erase supported water actuals.** Whole-row provenance parsing rejected otherwise valid water evidence when another component was unknown or corrected under a different boundary. Water provenance is now validated independently with its retained component identity.
6. **WARNING — supported legacy attestation was ignored.** Aggregate legacy actuals now reuse the existing value-bound attestation validator. Tampered values are rejected, and no per-device allocation is invented.
7. **WARNING — missing measurement could masquerade as aggregate water actuals.** A configured heater without a sensor now makes aggregate water provenance unknown; measured device contributions remain attributable. Fully unavailable water writes leave existing energy intact rather than writing a fabricated default zero.
8. **WARNING — rejected water spikes retained device progress.** The shared energy validator now invalidates water device attribution alongside a rejected aggregate, without mutating the original input metadata. A spike cannot reduce the quota or become a supported zero.
9. **WARNING — overlay plan/slot completion inconsistencies.** Live schedule water plans retain precedence over stale database plans, including the chart's separate planned field. Observation-only synthetic slots use their actual end boundary; current execution telemetry remains available without marking an unfinished slot historical. API tests assert aggregate/per-device water and grid preservation.
10. **WARNING — required rendered chart regression and estimate identification missing.** Real ChartCard render tests now verify the selected-slot panel and chart data for the current-slot/completion cases, unknown actuals, integrated zero, snapshot estimates and legacy actuals. Snapshot/mixed values are labelled estimates in details.
11. **WARNING — negative water power could inflate base load.** Live water disaggregation now clamps negative water power to zero consistently with recorded/history water energy, without changing EV behavior.
12. **WARNING — default/shared settings diverged from effective per-device semantics.** Omitted deferral now defaults to 6 in both progress and adapter. An obsolete shared gap cannot disable valid per-heater ceilings; top-up enablement and vacation remain the shared controls. Adapter regression covers enabled/disabled top-ups and a 28-hour heater gap.
13. **SUGGESTION — additive API types did not express the data.** Planned per-heater entries now have their actual `{heating_kw}` shape, nullable actual energies are typed as nullable, and supported legacy source is explicit.

14. **WARNING — coarse solver slots credited future delivery.** With supported 30/60-minute prices, the first solver slot can follow acquisition time. Progress now selects the solver quota bucket but bounds both stored observations and history integration by the acquisition instant. Real forecast/initial-state regressions prove only 0.85 kWh at 12:17 is credited, not hypothetical delivery through 12:30/13:00.
15. **WARNING — repeated-hour pipeline rounding failed.** Local pandas floor/ceil raised during both occurrences of the autumn repeated hour. Rounding now occurs in UTC before converting back to local time; both folds run through the real water scheduling pipeline.

## Task and requirement coverage

| Tasks | Production evidence | Regression evidence |
| --- | --- | --- |
| 1.1–1.3 | `backend/core/water_heating.py`; config router; defaults/settings types | Shared semantics tests cover midnight, shifted/fractional boundaries, DST, supported endpoints, invalid/non-finite inputs and omitted cutoff. Save tests prove valid 23/28/0.10 values persist and invalid saves leave bytes unchanged. |
| 2.1–2.2 | Shared normalization; slot integration; live recorder/backfill; load disaggregation | Recorder tests cover 60 W idle, mixed heating/idle integration, unchanged grid energy and single subtraction; normalization covers W/kW boundary equality. Existing load isolation/backfill tests exercise shared paths. |
| 2.3–2.4 | Versioned metadata parser; observation UPSERT; water interval accessor | Store tests cover measured zero, accepted correction, unrelated flags, restart reads, supported legacy sole ownership, ambiguous multiple heaters, changed ownership, tampered attestation and rejected spike attribution. |
| 3.1–3.4 | Forecasts → initial state → water progress → actual pipeline → adapter → solver | Both control modes run through the complete production path with whole-day prices. Stored/recent overlap, repeated reads, horizon advancement, recorded ownership, independent device values, rollover, outages and no-sensor controllability are checked. |
| 3.5 | Filtered activity → per-device block locking; outstanding quota | Mid-block tests preserve scheduled continuity and reject stale locks for measured idle. Quota tests retain outstanding partial/missed delivery, remove fulfilled quota and retain independent comfort top-ups. Existing executor control/shadow/idempotence tests remain part of the full suite. |
| 4.1–4.3 | Per-device Kepler recurrence and adapter enablement; existing settings widgets | Independent 28/8-hour deadbands; top-ups-off, vacation/horizon-start and comfort-weight tests; rendered settings help/bounds; valid persisted cutoff and actionable validation failures. |
| 5.1–5.4 | History API completion/provenance merge; chart series and details | API tests retain live current/future water, per-device and grid plans alongside current SoC. Actuals distinguish unsupported/default rows, zero, snapshot and valid legacy evidence. Rendered ChartCard tests exercise 18:56/current 18:45 slot and 19:00 completion. |
| 6.1–6.2 | Deterministic source-to-solver fixtures and change-local replay evidence | Both electrical control modes share proven accounting. Zero baseline versus partial fixed quota is explicit; completed quota, comfort and block continuity are isolated in solver/locking tests. The archive replay's missing inputs and inherited 7.743 kWh remain explicit. |
| 6.3 | Focused tests, full lint/check script, OpenSpec validation | Exact final results are recorded below. |

The coverage above maps all 11 requirements: per-device storage; normalization; measured progress; retry/continuity; daily quota buckets; gap recurrence; comfort weighting; validated settings; unfinished plans; component-evidenced actuals; and active-heating presentation. Their 41 named scenarios are covered by these combined production paths and regression groups; control mode does not introduce a separate electrical solver model.

## Validation

- Focused backend runs: 51 passed; expanded run 113 passed; subsequent focused run 85 passed; final settings/progress/API/recorder run 71 passed (160 existing PuLP deprecation warnings).
- Adapter/shared-semantics verification: 66 passed.
- Rendered chart/build-data/logic/settings tests: 42 passed across four files.
- Coarse-slot acquisition, whole-day pipeline and repeated-hour regression group: 15 passed (206 PuLP deprecation warnings). Live disaggregation/backfill group: 32 passed.
- Ruff check/format passed (219 Python files unchanged); Pyright: 0 errors, 0 warnings.
- Full backend final rerun: **2882 passed, 3009 warnings in 373.78 seconds**. Warnings include existing PuLP deprecations.
- Full frontend: formatting, ESLint and TypeScript passed; **549 tests passed across 59 files** (4.03 seconds).
- Strict OpenSpec change validation passed; `git diff --check` passed.
- Earlier run was deliberately interrupted at approximately 70% (exit 130, no test failures) after discovering the coarse-slot issue. The next complete backend run had **2881 passed, 1 failed, 3009 warnings in 375.17 seconds**: unchanged `/api/schedule` took 739 ms against its unchanged 500 ms threshold. The script stopped before frontend checks; all remaining steps were completed separately. The isolated dashboard performance group then passed 4/4 in 2.34 seconds, and the fresh full backend rerun passed all tests.
- The full rerun used temporary observation-only instrumentation in `/tmp`, without repository or threshold changes. The unchanged `/api/schedule` cold price-overlay dependency measured 128.32 ms, schedule YAML 0.18 ms and largest observed GC pause 1.38 ms. The endpoint reads the local schedule/config and shared price/forecast cache/fallback state; the changed API implementation starts in `today_with_history`. The exact cause of the earlier timing spike was not captured and is not claimed as fixed. No production performance workaround was added.

## Deliberate limits

No live Home Assistant, hardware or production SSH testing; no database schema/dependency/architecture changes; no runtime configuration, secrets or `docs/` edits; no staging, commits, pushes or archive.

Archive-derived 7.743 kWh remains inherited investigation evidence, not a newly integrated measurement. The archive replay uses explicit valid deferral 6 instead of invalid 30, isolates quota from comfort, and treats temperature mode as hypothetical. Raw heater history, the exact original solver input and backend termination proof were unavailable. Missing attribution or boundary-crossing aggregate intervals remain unknown unless reconstructable from power history. Deferral 30 requires explicit operator correction; cutoff 0 retains previous inclusion until configured.
