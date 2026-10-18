## Context

See proposal.md. Car energy is derived per slot in `backend/recorder.py` and stored in `ev_charger_observations.car_energy_kwh`. `planner/pipeline.py::_ev_delivered_today_kwh` sums `COALESCE(car_energy_kwh, energy_kwh * eff)`. `required_kwh` is a SoC delta (remaining), so `delivered/required` mixes units.

## Goals / Non-Goals

**Goals:** stop drift booking phantom energy; keep real reset handling; consistent card progress.
**Non-Goals:** migrating historical rows; changing loss learning or Kepler goal credit (they benefit from clean data).

## Decisions

1. **Reset rule.** A drop is a reset only if `cur <= energy_added_reset_threshold_kwh` (new optional per-charger key, default 0.5). Otherwise the step contributes 0 and the baseline moves to `cur`, so later rises still count.
2. **Wallbox cap.** After deriving sensor energy, `car = min(car, wallbox_kwh + tolerance)` with tolerance `max(0.05 kWh, 5% of wallbox)`; wallbox below ~0.01 kWh gives 0. SoC-sourced values are unchanged. Rationale: car-side energy can never physically exceed grid-side energy; the tolerance covers sensor granularity and slot boundary skew.
3. **Rejected aggregates.** Where `ev_charger_energy` is zeroed (~583), also zero `ev_charger_car_energy`.
4. **Defensive read.** `_ev_delivered_today_kwh` caps each slot's car value at `energy_kwh + tolerance` in SQL (`MIN`), so existing bad rows stop inflating the card without a migration.
5. **Progress (decision: no persistence, no schema change; user-confirmed split by SoC availability).** Goal-start SoC does not exist anywhere in the backend (grep: no `start_soc`/goal-start in planner, API, or frontend) and is NOT persisted. With SoC: percent = `soc / target_soc * 100`, clamped 0-100, 100 when soc >= target, hidden when SoC or target is null. Uses only fields already in the charger state (`soc_percent`, `target_soc_percent`). "Delivered Today" stays as a plain informational figure. Without a SoC sensor: the bar is kept and computed as delivered / required kWh, where delivered already reduces `required_kwh` for such chargers (`_calculate_required_kwh`, planner/pipeline.py:~448), so total required = delivered + remaining; clamped 0-100. The "Target X kWh (N% of goal)" label is replaced by SoC text (e.g. "62% to 80%").

## Risks / Trade-offs

- **Plug-in dropped.** Verified: `backend/recorder.py` has no plug input; it fetches only `energy_added_sensor`/`soc_sensor` history. Plug transitions exist only live in `backend/ha_socket.py` (events, in-memory last state in `backend/core/ev_plug.py`), not per slot, and fetching plug history would add a new dependency. So reset = near-zero value only; a reset to a non-zero value (e.g. new session read late) is missed (under-count, safe), and the wallbox cap bounds any mistake.
- Cap may undercount if the wallbox meter is missing; then wallbox ~0 yields 0 car energy and the SoC fallback in goal accounting still applies.

## Resolved questions (verified in code)

- Where delivered energy matters for planning: `_calculate_required_kwh` (planner/pipeline.py:410-453) ignores delivered-today whenever SoC is known or a `soc_sensor` is configured; it subtracts `_ev_delivered_today_kwh` only for chargers with no SoC sensor at all. Such chargers can still have `energy_added_sensor`, so phantom energy would shrink their remaining need; decision 4 (read cap) protects this path too.
- Reset threshold config: parsed per charger from the raw config dict in the recorder (`ev.get(...)`, backend/recorder.py:117,150 pattern); range validation goes next to `_EV_LOSS_RANGES` (backend/api/routers/config.py:726-730, used at :1177) as `"energy_added_reset_threshold_kwh": (0.0, 5.0, "kWh")`. The executor config dataclass (executor/config.py:184,924) does not need the key because the executor does not read it. Default added at config.default.yaml near :162.
- Line ~583 zeroing: backend/recorder.py:583-584 zeroes `ev_charger_energy` when the aggregate `ev_charging_kwh` is falsy; `ev_charger_car_energy` (set at :540) is the sibling to zero there.
- Frontend state fields exist: `EVChargerState.soc_percent` and `target_soc_percent` (frontend/src/lib/api.ts:1317,1323). Current bar at EVChargingCard.tsx:60-64,303,530-541 uses delivered/required; the "Target X kWh (N% of goal)" text is at :534; `complete` badge at :118. Existing test file: frontend/src/components/EVChargingCard.status.test.ts:47.
- Chargers without a SoC sensor (user decision): keep the progress bar, computed as delivered / required kWh. Chargers with SoC use soc / target_soc.
- The 90.7 vs ~111 kWh explanation remains inference (planner output cached); not verifiable without logs and does not affect the fix.

## Fixture: torleif 2026-10-18 (ev_charger_1, from `planner_learning.db`, read-only copy)

Config: `energy_added_sensor: sensor.tillford_laddningsenergi`, charge_efficiency 0.95. Raw sensor values are not in the diagnostics (recorder only logs "history energy"); the stored `car_energy_kwh` is the only evidence. Slot starts are local (+02:00, no DST change until 10-25). Format: slot, energy_kwh (wallbox), car_energy_kwh (stored, buggy). Wallbox is 7.5e-05 in every slot not listed as different.

| slot | energy_kwh | car_energy_kwh (buggy) | expected after fix |
|---|---|---|---|
| 00:30 | 7.5e-05 | 0.84 | 0 |
| 00:45 | 7.5e-05 | 0.33 | 0 |
| 01:00 | 7.5e-05 | 0.11 | 0 |
| 04:45 | 7.5e-05 | 0.15 | 0 |
| 05:00 | 7.5e-05 | 22.47 | 0 |
| 05:45 | 7.5e-05 | 22.36 | 0 |
| 06:30 | 7.5e-05 | 22.25 | 0 |
| 07:45 | 7.5e-05 | 22.14 | 0 |
| 08:30 | 7.5e-05 | 22.03 | 0 |
| 09:30 | 7.5e-05 | 21.92 | 0 |
| 10:45 | 0.2966 | 0.0 | unchanged (0.0) |
| 11:00 | 0.6433 | 41.86 | <= 0.6433 + tolerance (0.05); unplug logged at 11:10 inside this slot |
| 13:45 | 0.4363 | 0.0 | unchanged |
| 14:00 | 0.1382 | 0.44 | <= 0.1882 (cap) |
| 14:15 | 0.4397 | 0.44 | unchanged (within cap 0.4897) |
| 14:45 | 7.5e-05 | 0.77 | 0 |

All other slots 00:00-14:45 have car 0.0 and wallbox 7.5e-05. Drops are ~0.11 kWh per 45-60 min (22.47 -> 22.36 -> 22.25 -> 22.14 -> 22.03 -> 21.92); each drop is booked as the whole new value. The 14:00 and 14:45 rows show the cap also matters for small rises (0.44, 0.77 with wallbox ~0). Unit-test the sequence by feeding sensor histories reconstructed from the drift values (22.58 start, -0.11 steps) with the wallbox energies above; do not assert the 11:00 / 14:00 raw sensor inputs (unknown), only that the cap holds.

### Explaining 90.7 kWh at 08:55 vs ~111 sum

Sum of stored car values for slots 00:00-08:45 is 112.68 (111.25 from the five drift rows 22.47...22.03, plus 1.43 small rows); 112.68 also matches the "~111". 90.7 equals 22.47+22.36+22.25+22.14 + 1.43 = 90.65, i.e. the state before the 08:30 row (recorded 08:45 local) landed. The "today" boundary is not the cause: local midnight on 10-18 is +02:00 and slot_start strings are +02:00, so the string comparison in `_ev_delivered_today_kwh` is consistent. Most likely the card value came from the last planner run before the 08:30 row was written (planner output is cached, not live). This is inference, not verified from logs. 14:30 total: 177.34 (matches the 176.5 reported within a row).
