## 1. Live config reload

- [x] 1.1 `executor/actions.py`: add `ActionDispatcher.update_config(config)` (config + shadow_mode)
- [x] 1.2 `executor/engine.py`: `reload_config()` only stores the new config/profile; tick start (under `_tick_lock`, ~1551) snapshots `self.config`/profile and applies them to the dispatcher; tick body uses the snapshot
- [x] 1.3 Re-audit long-lived holders of `ExecutorConfig` (load balancer, controller, water/EV helpers) and fix any found
- [x] 1.4 Regression test (`tests/`, executor): change `soc_target`, touch config mtime, `reload_config()`, run a SoC write, assert the new entity is called and the old is not
- [x] 1.5 Test: reload from another thread mid-tick; that tick keeps the old entity, next tick uses the new one

## 2. Deye profile

- [x] 2.1 `profiles/deye.yaml`: `soc_target` default `number.inverter_program_6_soc`, domain `number`, match domains `[number, input_number]`, regex per design
- [x] 2.2 Entity-matching tests: program 6 ranks first, programs 1-5 do not match, helper still matches; config with helper loads without error
- [x] 2.3 Add `setup_notice` to Deye metadata

## 3. Setup notice

- [x] 3.1 `executor/profiles.py`: `ProfileMetadata.setup_notice`, parsing, validation, `list_profiles()` output
- [x] 3.2 `profiles/schema.yaml`: document the field
- [x] 3.3 Tests: valid, absent, invalid severity/type
- [x] 3.4 Frontend: render notice in onboarding profile step (`components/onboarding/steps.tsx`) and Settings > System (`SystemTab.tsx` / `ProfileSetupHelper.tsx`) per `docs/design-system/AI_GUIDELINES.md`; extend API types
- [x] 3.5 Vitest: shown for Deye, hidden for profile without notice

## 4. Program time check

- [x] 4.1 Pure `derive_program_time_entities(soc_entity)` + unit tests (Solarman name, helper → None, no number → None, program 1..6 input)
- [x] 4.2 `backend/health.py` (near ~731): Deye-only check, warning on mismatch only
- [x] 4.3 Expose verify status (ok / mismatch / unverifiable) to the frontend; `OnboardingWizard.tsx` and Settings notice show dismissible "Couldn't verify program times" reusing existing dismiss patterns, dismissal persisted
- [x] 4.4 Tests: all 00:00 ok, one differs warning, missing/unavailable gives no health issue; vitest for dismiss persistence

## 5. Docs

- [x] 5.1 `docs/SETUP_GUIDE.md`: Deye section (~line 17) and work-mode table note (~line 91) on program 6 + 00:00 times
- [x] 5.1b Fallback section: if program 6 does not take effect on your model, use the master SoC helper + example HA automation copying it to all 6 program SoCs
- [x] 5.2 `docs/inverter-profiles/CREATING_INVERTER_PROFILES.md`: document `setup_notice`
- [x] 5.3 Do not touch `docs/RELEASE_NOTES.md`

## 6. Verify

- [x] 6.1 `./scripts/lint.sh` and targeted pytest/vitest
