## 1. Source helper and planner

- [x] 1.1 Add `active_water_heaters(config)` to `backend/core/water_heating.py` (flag default true, enabled filter; id-less entries kept as at HEAD)
- [x] 1.2 `planner/pipeline.py`: derive `water_heaters_cfg` and `enabled_heater_ids` from the helper
- [x] 1.3 `pipeline.py` vacation branch: skip anti-legionella record read/write and rebuild when flag off
- [x] 1.4 `planner/solver/adapter.py:539`: use the helper
- [x] 1.5 Test: vacation + flag off + anti-legionella due yields no water plan and no record read/write (`tests/planner/`)
- [x] 1.6 Tests: adapter returns no heaters when flag off; mid-block detection yields no forced slots when flag off

## 2. Backend paths

- [x] 2.1 Gate `validate_water_heating_config` on the flag; test stale invalid value with flag off and on
- [x] 2.2 `backend/loads/service.py`: no water loads when flag off; test in `tests/loads/`
- [x] 2.3 `backend/ha_socket.py:111`: default true, use the helper; tests for missing flag and flag off
- [x] 2.4 `backend/api/routers/schedule.py`: mask water fields when flag off; test in `tests/api/`
- [x] 2.5 Test: health and config-save emit no water issues when flag off (`tests/health/`, config tests)

- [x] 2.6 `backend/recorder.py:432-441`: derive `water_config` from `active_water_heaters(config)` and drop the unconditional `unknown` override at `:440` (it must only apply to active heaters with no sensor)
- [x] 2.7 Test (`tests/`, recorder): exact PLL config (`has_water_heater: false`, `water_heaters: [{id: main_tank, enabled: true, sensor: "", target_entity: ""}]`) records water `method == disabled_zero`, `water_kwh == 0.0`, and `backend/grid_only_comparison.py` usability accepts the slot; control case with flag true yields `unknown`
- [x] 2.8 Test: flag false with empty `water_heaters` and flag missing (default true) with sensorless heater

## 3. Frontend

- [x] 3.1 CommandBar: hide boost, heater selector, water pills and vacation controls when flag off (pass `hasWaterHeater`)
- [x] 3.2 Dashboard: gate boost and vacation banners
- [x] 3.3 ChartCard: drop water datasets, strip marks and legend when flag off
- [x] 3.4 WaterTab: disabled notice
- [x] 3.5 Vitest for each of 3.1 to 3.4

## 3b. Grid-only comparison with unmeasured water

- [x] 3b.1 `backend/grid_only_comparison.py`: accept water `unknown` under the rule in design.md; null water to 0 in `_slot_costs`; clamp-suspect rejection
- [x] 3b.2 Add `coverage.water_unmeasured_slots` and `water_unmeasured_hours` to the response for all periods
- [x] 3b.3 Backend tests (`tests/`, grid-only): PLL slot included with note; null-water slot included; disaggregated/snapshot/mixed load + water unknown rejected; clamp-suspect (EV>0, load 0) rejected; EV unknown and load unknown rejected; mixed day counts and cost totals; Kristofer-like fixture (~851 water-unknown derived_history slots across 7d/30d) fully included with correct hours; torleif-like fixture shows 0 and no note
- [x] 3b.4 `CommandDomains.tsx`: warning note "Water not measured for N h, included" beside coverage, per `docs/design-system/AI_GUIDELINES.md`; extend API types
- [x] 3b.5 Vitest: note shown for count above 0 (today and 30d payloads), hidden at 0, coexists with "(n excluded)"

## 4. Verify

- [x] 4.1 `./scripts/lint.sh` and targeted pytest/vitest
- [x] 4.2 `openspec validate water-heater-disabled-guard --strict`
