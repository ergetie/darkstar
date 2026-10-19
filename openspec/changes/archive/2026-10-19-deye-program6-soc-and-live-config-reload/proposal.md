## Why

Entity changes saved in Settings do not reach the executor until restart. `ExecutorEngine.reload_config()` (`executor/engine.py` ~504) replaces `self.config`, but `ActionDispatcher` (`executor/actions.py`, built ~494 with the old `ExecutorConfig`) keeps the old object; only `shadow_mode` and `profile` are pushed. Entity resolution (`actions.py` ~532/536, ~836, 1087, 1179) and notifications (~1512) read the stale config. Seen in prod: `soc_target` changed to `number.inverter_program_6_soc`, executor still showed "Soc Target SKIPPED input_number.master_soc_target".

Separately, the Deye profile defaults `soc_target` to the helper `input_number.master_soc_target`, which needs a user automation copying it into all six Time of Use program SoCs. With all six program times at 00:00, program 6 is the active program (tested on a real Deye LV 3-phase hybrid; also reported in batpred discussion #3624), so Darkstar can write program 6 SoC directly.

## What Changes

- Executor: `reload_config()` stores the new config; each tick snapshots it at start and applies it to the dispatcher, so a tick never sees a mid-tick swap (reloads also come from API threads). Regression tests: entity change takes effect next tick; mid-tick reload does not leak into the running tick.
- Deye profile: `soc_target.default_entity` becomes `number.inverter_program_6_soc`; match rules accept `number` and `input_number` and an `entity_id_regex` that finds program 6 SoC as well as the legacy `soc_target` helper. Any entity still allowed.
- Profiles: new optional `metadata.setup_notice` (title + markdown-free text lines, severity info/warning), validated in `executor/profiles.py`, exposed by `list_profiles()`, and shown in onboarding and Settings > System when that profile is selected.
- Deye setup notice: set all six program times to 00:00, enable Time of Use; Darkstar controls program 6 SoC; the old master SoC helper automation is no longer needed.
- Health check: for the Deye profile, warn (not error) when program times are found and not all 00:00. Time entities are derived from `soc_target` (soc→time naming). If they cannot be verified, only the onboarding/setup notice shows a dismissible info (dismissal persisted); no health issue.
- Docs: fallback to the master SoC helper + example automation if program 6 does not take effect on a model.
- Docs: `docs/SETUP_GUIDE.md` and `docs/inverter-profiles/CREATING_INVERTER_PROFILES.md` (approved by the user). `docs/RELEASE_NOTES.md` is not touched.

## Capabilities

### New Capabilities
- `inverter-profile-setup`: profile setup notice and Deye program-time verification.

### Modified Capabilities
- `executor`: config reload reaches the action dispatcher.
- `entity-matching`: Deye `soc_target` default and match rules.

## Impact

Files: `executor/engine.py`, `executor/actions.py` (maybe a setter), `executor/profiles.py`, `profiles/deye.yaml`, `profiles/schema.yaml`, `backend/health.py`, `frontend/src/components/onboarding/{steps,OnboardingWizard}.tsx`, `frontend/src/pages/settings/{SystemTab,components/ProfileSetupHelper}.tsx`, docs above, tests. No DB schema or dependency changes. Existing installs keep their configured `soc_target`; only defaults and suggestions change.
