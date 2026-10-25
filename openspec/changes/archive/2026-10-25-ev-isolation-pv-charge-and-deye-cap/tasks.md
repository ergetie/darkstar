## 1. Controller: isolation in the PV-charge branch

- [x] 1.1 In `executor/controller.py` add `EV_ISOLATION_REASON = "EV charging, blocking battery discharge"` beside `HOLD_MARGIN_REASON` (~L36-38).
- [x] 1.2 In `_follow_plan`, PV-charge branch (`elif slot.charge_kw > 0`, ~L267-270): `plan_state.enter(None, None)`; if `ev_isolating` set `mode_intent = "idle"` and `note = EV_ISOLATION_REASON`, else `"self_consumption"`. Also set the same note in the existing isolation idle branch (~L271-278) and update the branch comments. Grid-charge and export branches stay as they are.
- [x] 1.3 Confirm no existing test pins the reason text of the isolation idle branch (grep `tests/executor`); adjust if one does.

## 2. Controller: max charge unless export is planned

- [x] 2.1 In `_follow_plan` (~L338-342) change the self_consumption override to: `mode_intent == "self_consumption" and (charge_value <= 0 or slot.export_kw <= 0)` sets `charge_value = max_charge` and `write_charge = True`. Update the comment. Do not touch `_calculate_charge_limit` or the legacy `grid_charge_planned` expression (~L237-241).

## 3. Tests

- [x] 3.1 `tests/executor/test_ev_isolation.py` (controller class), PV-charge slot (`charge_kw` > 0, `grid_charge_kw=0`, `export_kw=0`): `discharge_blocked_by_ev=True` gives `idle` and the reason contains `EV_ISOLATION_REASON`; `ev_charging_kw=0.5` gives `idle`; keep-on only gives `idle`.
- [x] 3.2 Same file: min-SoC guard engaged (live SoC at `min_soc_percent`) with an isolated PV-charge slot stays `idle` with the isolation reason, latch still engaged; grid charge below target with `discharge_blocked_by_ev=True` still gives `charge`; PV-charge slot with no EV trigger still gives `self_consumption`.
- [x] 3.3 `tests/executor/test_executor_controller.py`: self_consumption PV-charge slot with `export_kw == 0` gives `charge_value == max_charge_a` (and `max_charge_w` with a W profile) and `write_charge_current` True; with `export_kw > 0` gives the planned capped value (existing `test_pv_surplus_uses_planned_charge_limit`); grid-charge `charge` mode still gives the planned `charge_value` (existing Deye migration and watt tests ~L94 stay green).
- [x] 3.4 `tests/executor/test_battery_plan_tracking.py` and the Deye profile tests (`tests/executor/test_executor_deye_migration.py`, `tests/executor/test_profiles_v2.py`): grep `tests/executor` for tests that pin the old cap (zero-export PV-charge slot expecting planned `charge_value`, or solar-only expecting `self_consumption` under isolation); update them. Add a Deye check that a zero-export PV-charge decision writes `max_charge_current` as the configured max.
- [x] 3.5 Update the solar-only isolation expectation in any test of "EV isolation preserves solar-only charging" (mode now `idle`, not `self_consumption`).

## 4. Verification

- [x] 4.1 Run `UV_NO_SYNC=1 uv run python -m pytest tests/executor -q` and fix regressions.
- [x] 4.2 Run `./scripts/lint.sh` once. Known unrelated failures: 2 date-dependent tests in `tests/planner/test_schedule_history_overlay.py`.
- [x] 4.3 Run `openspec validate ev-isolation-pv-charge-and-deye-cap --strict`.
