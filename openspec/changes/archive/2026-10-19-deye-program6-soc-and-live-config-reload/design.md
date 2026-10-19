## Context

- `ExecutorEngine.reload_config()` holds `self._lock`, reloads `self.config`, updates `status`, `_load_balancer.config`, `dispatcher.shadow_mode`, and `dispatcher.profile` (only on profile change).
- Audit of other holders of the config object: `LoadBalancer` gets `config.load_balancing` reassigned in reload (ok). The controller (`make_decision`, `engine.py` ~1945) and the controller built ~584 receive `self.config.*` per call (ok). Water and EV helpers in the engine read `self.config` live (ok). `ActionDispatcher` is the only long-lived stale holder found.
- Deye profile `soc_target` match today: `domain: [input_number]`, `entity_id_regex: "soc[ _]target"`. A `number.*program_6_soc` entity can never match.
- `ProfileMetadata` fields: name, version, schema_version, description, supported_brands, detect, role_overrides. No notice field.

## Decisions

1. **Dispatcher config propagation (tick-boundary swap).** Verified: the tick does not hold `self._lock`; it uses `_tick_lock` (engine.py ~1551, non-blocking). `reload_config()` runs from the loop before each tick (~1427) and from API threads (`backend/api/routers/config.py` ~373, executor routers ~135/437/527), so a reload can land mid-tick. Therefore `reload_config()` only stores the new `self.config`. At tick start the tick snapshots `self.config` once and calls `ActionDispatcher.update_config(snapshot)` (config + shadow_mode) before executing; the whole tick uses that snapshot. The dispatcher config never changes mid-tick. Profile swap follows the same rule (applied at tick start).
2. **Deye default.** `default_entity: number.inverter_program_6_soc`, `domain: number`, match `domain: [number, input_number]`, `entity_id_regex: "(prog(ram)?[ _]?6[ _].*soc|soc[ _]target)"`. Scoring ranks program 6 above the helper; programs 1-5 do not match.
3. **Setup notice schema.** `metadata.setup_notice: {title: str, severity: info|warning, items: [str]}`. Optional. Validation rejects wrong types and unknown severity. Exposed as `setup_notice` in `list_profiles()` and the profile API. Frontend renders it with the design-system Banner/notice tokens (`docs/design-system/AI_GUIDELINES.md`) in the onboarding profile step and under the profile selector in Settings > System.
4. **Program time derivation.** Pure function `derive_program_time_entities(soc_entity) -> list[str] | None`:
   - Match `^(number|input_number)\.(.*?)(prog(?:ram)?[ _]?)([1-6])([ _].*)$`. Fail → None.
   - Build `time.<prefix><p><N><suffix with soc→time>` for N=1..6; replace only the last `soc` token in the suffix.
   - Examples: `number.inverter_program_6_soc` → `time.inverter_program_1_time` ... `_6_time`.
   - `input_number.master_soc_target` → None (no program number).
   - Default derivation assumes `soc`/`time` naming (user expects all integrations to use it).
5. **Health check.** In `backend/health.py` (next to the existing `executor.inverter` entity validation ~731), Deye profile only: read the six states. All `00:00`/`00:00:00` → ok. Times found but any different → warning listing entities and values. Never an error, never blocks the executor.
6. **"Couldn't verify" is onboarding-only.** When derivation fails or entities are missing/unavailable, health reports nothing. Instead the Deye setup notice (onboarding in `OnboardingWizard.tsx` and Settings) shows an info line "Couldn't verify program times", dismissible with persisted dismissal, reusing the wizard's existing dismiss pattern. Helper users get no permanent warning.
7. **Fallback documented.** If program 6 does not take effect on a model, docs describe the old setup: master SoC helper + HA automation copying it to all 6 program SoCs, with an example automation.

## Risks / Uncertainty

- Integration naming is not verified in this repo (no `program_N` entities anywhere outside this change). Solarman (`program_N_soc` / `program_N_time`) fits the pattern. kellerza sunsynk naming (`prog6_capacity`, `prog6_time`?) is unknown: "capacity" instead of "soc" would not derive; such setups get the dismissible "couldn't verify" note. Some integrations expose time as `select` or `text`, not `time`; derivation assumes `time` and otherwise falls back to the same note.
- Program 6 being active with all times 00:00 is verified on one LV 3-phase model plus community reports; HV/single-phase models unverified; mitigated by the documented helper fallback.
