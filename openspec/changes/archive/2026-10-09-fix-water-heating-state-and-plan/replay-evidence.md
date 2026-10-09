# Water-heating replay evidence

## Deterministic regression

`tests/backend/test_water_progress_pipeline.py::test_store_initial_state_adapter_solver_credits_progress_once` exercises the persisted-observation → initial-state/history → per-heater adapter → solver path for both switch and temperature control. A stored 0.75 kWh interval plus the uncovered 15 minutes of 3 kW history yields 1.50 kWh at the cutoff. Re-reading the same cutoff leaves progress at 1.50 kWh; advancing by 15 minutes yields 2.25 kWh. This covers recorder lag, interval overlap, restart reads and a later replan without double counting. The fixed plan schedules 4.50 kWh of the 6 kWh quota; a zero-progress baseline schedules 6.00 kWh. A separate solver regression verifies completed quota removes quota demand while an enabled comfort ceiling can still schedule a top-up.

## Archived Oct 8 schedule

The replay used the diagnostic archive’s saved 105-slot schedule, load/PV forecasts, prices, starting SoC and single 3.1 kW heater configuration. The archive config sets `defer_up_to_hours: 30`, which the new supported range rejects. For this comparison only, the replay explicitly set the valid shipped default of 6 hours so the supplied Oct 8 progress was charged to the Oct 8 06:00–Oct 9 06:00 quota bucket. It disabled EV charging and gap-comfort penalties to isolate the daily quota. Progress inputs were 0 kWh and the investigation’s archive-derived 7.743 kWh active-slot total; the 9.087 kWh meter total, which includes idle draw, was not used. The archived actuator is a switch; temperature mode is shown as a hypothetical planner-equivalent case.

| Control mode | Progress | Oct 8 06:00 quota bucket | Oct 9 06:00 quota bucket |
|---|---:|---:|---:|
| switch | 0.000 kWh | 3.875 kWh | 3.875 kWh |
| switch | 7.743 kWh | 0.000 kWh | 3.875 kWh |
| temperature (hypothetical) | 0.000 kWh | 3.875 kWh | 3.875 kWh |
| temperature (hypothetical) | 7.743 kWh | 0.000 kWh | 3.875 kWh |

The 3.875 kWh plan is the solver’s soft-minimum outcome and is not rounded up to 4 kWh. The replay’s Kepler result flag was true; this is not independent evidence of a proven solver optimum because the diagnostic export does not retain the replay’s raw backend termination proof.

The archive includes a saved schedule/config and aggregate observations, but not the raw heater-power history series, the exact historical LP/input, or backend incumbent/bound/termination output. The 7.743 kWh value is carried forward from the existing archive investigation rather than re-integrated here. The replay is therefore an archived quota comparison, not a full re-execution of the deployed run or a thermal/hardware test.

## Independent verification of the complete production path

The original deterministic regression called initial-state acquisition and the adapter directly. Independent verification additionally found that the forecast orchestrator supplied midnight (the first price of the whole day), while the actual pipeline filtered the solver horizon to the current slot. The new `test_whole_day_forecasts_and_real_pipeline_use_first_solver_slot` writes a real observation, supplies whole-day prices through `get_all_input_data`, and runs `PlannerPipeline.generate_schedule` through the real adapter and solver. Both switch and temperature modes credit 0.75 kWh at a midday cutoff; advancing the solver horizon by 15 minutes credits 1.50 kWh. History overlaps the persisted observation and does not double count it. This also verifies refreshing progress if acquisition and optimization cross a slot boundary.

Additional regressions verify a quota boundary at 06:07:30 splits a constant 15-minute planned slot across both buckets, and stored progress from the second occurrence of the autumn DST hour is retained even when its wall-clock label precedes the first occurrence's quota boundary. Missing history remains incomplete rather than a fabricated zero. A stored interval crossing a quota boundary is reconstructed from raw history when available; its aggregate is never proportionally relabelled as measured energy.

Rendered `ChartCard` tests select the 18:45–19:00 Stockholm slot at 18:56 and at 19:00. They assert the retained planned chart dataset and rendered details for unavailable actuals, integrated zero, snapshot estimates and explicitly supported legacy aggregate actuals. Snapshot-derived details identify the value as an estimate. API regressions separately establish current-slot grid/per-heater plan preservation despite stale database plans and valid current SoC telemetry.

These additional regressions are synthetic, deterministic software evidence. They do not add measurements to, or strengthen the historical provenance of, the archived Oct 8 replay above.

Independent verification also exercises supported 30/60-minute price acquisition at 12:17: the upcoming solver cutoff is 12:30/13:00, while credited measured delivery remains 0.85 kWh through acquisition. Both occurrences of the autumn repeated hour run through the real water scheduling pipeline; UTC slot rounding preserves their distinct instants.
